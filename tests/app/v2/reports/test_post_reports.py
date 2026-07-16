import json

import pytest

from app.dao.reports_dao import get_report_by_id
from app.models import ReportStatus
from app.v2.reports import reports_api_enabled
from tests import create_authorization_header


@pytest.mark.parametrize(
    "environment, expected",
    [
        ("development", True),
        ("dev", True),
        ("staging", True),
        ("test", True),
        ("scratch", True),
        ("production", False),
        ("production_ff", False),
    ],
)
def test_reports_api_enabled_hides_endpoints_in_production(environment, expected):
    assert reports_api_enabled(environment) is expected


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
