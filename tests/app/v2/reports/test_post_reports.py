import json

from app.dao.reports_dao import get_report_by_id
from app.models import ReportStatus
from tests import create_authorization_header


def test_post_report_returns_202(client, sample_service, mocker, create_api_key_with_manage_reports_perm):
    mock_task = mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email", "language": "en"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 202
    resp_json = json.loads(response.get_data(as_text=True))
    report = get_report_by_id(resp_json["report_id"])
    assert str(report.service_id) == str(sample_service.id)
    assert report.status == ReportStatus.REQUESTED.value
    assert report.requesting_user_id is None
    assert report.language == "en"
    assert response.headers["Location"] == f"/v2/reports/{report.id}"
    mock_task.assert_called_once_with([str(report.id), []], queue="generate-reports")


def test_post_report_requires_language(client, mocker, create_api_key_with_manage_reports_perm):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400


def test_post_report_rejects_invalid_language(client, mocker, create_api_key_with_manage_reports_perm):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email", "language": "es"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400


def test_post_job_report_requires_job_id(client, mocker, create_api_key_with_manage_reports_perm):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "job", "language": "en"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400


def test_post_job_report_with_job_id_returns_202(client, sample_job, mocker, create_api_key_with_manage_reports_perm):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "job", "language": "en", "job_id": str(sample_job.id)}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 202
    report = get_report_by_id(json.loads(response.get_data(as_text=True))["report_id"])
    assert str(report.job_id) == str(sample_job.id)


def test_post_report_rejects_invalid_report_type(client, mocker, create_api_key_with_manage_reports_perm):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "invalid", "language": "en"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400


def test_post_report_returns_403_without_manage_reports_permission(client, mocker, create_api_key_no_perm):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_no_perm)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email", "language": "en"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 403
    data = json.loads(response.get_data(as_text=True))
    assert "manage reports" in data["errors"][0]["message"].lower()


def test_post_report_requires_authentication(client):
    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email"}),
        headers=[("Content-Type", "application/json")],
    )

    assert response.status_code == 401
