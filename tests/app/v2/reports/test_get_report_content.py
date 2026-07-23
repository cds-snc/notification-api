import uuid

import botocore.exceptions
import pytest

from app.dao.reports_dao import create_report
from app.models import Report, ReportStatus, ReportType
from tests import create_authorization_header
from tests.app.db import create_service


def _make_report(service_id, status=ReportStatus.READY.value, url="https://s3.example.com/report.csv"):
    return Report(
        id=uuid.uuid4(),
        report_type=ReportType.EMAIL.value,
        service_id=service_id,
        status=status,
        requesting_user_id=None,
        language="en",
        url=url,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_get_report_content_streams_csv(client, sample_service, create_api_key_with_manage_reports_perm, mocker):
    report = _make_report(sample_service.id)
    create_report(report)

    csv_data = b"recipient,status\nfoo@example.com,delivered\n"
    mock_stream = mocker.patch(
        "app.v2.reports.get_report_content.stream_report_from_s3",
        return_value=iter([csv_data]),
    )

    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    response = client.get(
        path=f"/v2/reports/{report.id}/content",
        headers=[auth_header],
    )

    assert response.status_code == 200
    assert response.data == csv_data
    assert "text/csv" in response.content_type
    assert f'filename="{report.id}.csv"' in response.headers["Content-Disposition"]
    mock_stream.assert_called_once_with(sample_service.id, report.id)


def test_get_report_content_streams_large_file_in_chunks(client, sample_service, create_api_key_with_manage_reports_perm, mocker):
    report = _make_report(sample_service.id)
    create_report(report)

    chunks = [b"a" * (1024 * 1024), b"b" * (1024 * 1024), b"c" * 500]
    mocker.patch(
        "app.v2.reports.get_report_content.stream_report_from_s3",
        return_value=iter(chunks),
    )

    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    response = client.get(
        path=f"/v2/reports/{report.id}/content",
        headers=[auth_header],
    )

    assert response.status_code == 200
    assert response.data == b"".join(chunks)


# ---------------------------------------------------------------------------
# Auth / permission errors
# ---------------------------------------------------------------------------


def test_get_report_content_returns_403_without_manage_reports_permission(client, sample_service, create_api_key_no_perm):
    report = _make_report(sample_service.id)
    create_report(report)

    auth_header = create_authorization_header(api_key=create_api_key_no_perm)
    response = client.get(
        path=f"/v2/reports/{report.id}/content",
        headers=[auth_header],
    )

    assert response.status_code == 403


def test_get_report_content_returns_401_with_no_auth(client, sample_service):
    report = _make_report(sample_service.id)
    create_report(report)

    response = client.get(path=f"/v2/reports/{report.id}/content")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


def test_get_report_content_returns_404_for_nonexistent_report(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    response = client.get(
        path=f"/v2/reports/{uuid.uuid4()}/content",
        headers=[auth_header],
    )

    assert response.status_code == 404


def test_get_report_content_returns_404_for_report_belonging_to_other_service(
    client, sample_service, notify_db_session, create_api_key_with_manage_reports_perm
):
    other_service = create_service(service_name="other service for content test")
    report = _make_report(other_service.id)
    create_report(report)

    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    response = client.get(
        path=f"/v2/reports/{report.id}/content",
        headers=[auth_header],
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Report not ready
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [ReportStatus.REQUESTED.value, ReportStatus.GENERATING.value, ReportStatus.ERROR.value],
)
def test_get_report_content_returns_409_when_report_not_ready(
    client, sample_service, create_api_key_with_manage_reports_perm, status
):
    report = _make_report(sample_service.id, status=status)
    create_report(report)

    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    response = client.get(
        path=f"/v2/reports/{report.id}/content",
        headers=[auth_header],
    )

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# S3 errors
# ---------------------------------------------------------------------------


def test_get_report_content_returns_502_on_s3_error(client, sample_service, create_api_key_with_manage_reports_perm, mocker):
    report = _make_report(sample_service.id)
    create_report(report)

    mocker.patch(
        "app.v2.reports.get_report_content.stream_report_from_s3",
        side_effect=botocore.exceptions.ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
            "GetObject",
        ),
    )

    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    response = client.get(
        path=f"/v2/reports/{report.id}/content",
        headers=[auth_header],
    )

    assert response.status_code == 502
