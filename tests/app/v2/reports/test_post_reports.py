import json

from app.config import configs
from app.dao.reports_dao import get_report_by_id
from app.models import ReportStatus
from tests import create_authorization_header


def test_report_api_disabled_by_default_in_production():
    # The feature must stay hidden in production unless FF_REPORT_API is explicitly enabled.
    assert configs["production"].FF_REPORT_API is False


def test_post_report_returns_202(client, sample_service, mocker):
    mock_task = mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(service_id=sample_service.id)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 202
    resp_json = json.loads(response.get_data(as_text=True))
    report = get_report_by_id(resp_json["report_id"])
    assert str(report.service_id) == str(sample_service.id)
    assert report.status == ReportStatus.REQUESTED.value
    assert report.requesting_user_id is None
    assert response.headers["Location"] == f"/v2/reports/{report.id}"
    mock_task.assert_called_once()


def test_post_job_report_requires_job_id(client, sample_service, mocker):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(service_id=sample_service.id)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "job"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400


def test_post_job_report_with_job_id_returns_202(client, sample_job, mocker):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(service_id=sample_job.service_id)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "job", "job_id": str(sample_job.id)}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 202
    report = get_report_by_id(json.loads(response.get_data(as_text=True))["report_id"])
    assert str(report.job_id) == str(sample_job.id)


def test_post_report_rejects_invalid_report_type(client, sample_service, mocker):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(service_id=sample_service.id)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "invalid"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400


def test_post_report_requires_authentication(client):
    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email"}),
        headers=[("Content-Type", "application/json")],
    )

    assert response.status_code == 401
