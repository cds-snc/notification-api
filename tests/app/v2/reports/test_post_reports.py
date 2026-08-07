import json
import math

from app.dao.reports_dao import get_report_by_id
from app.models import ReportStatus
from app.v2.reports.post_reports import REPORT_RATE_LIMIT, REPORT_RATE_WINDOW
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


def test_post_report_rate_limit_returns_429(client, sample_service, mocker, create_api_key_with_manage_reports_perm):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    fixed_now = 1_700_000_000.0
    seconds_to_wait = REPORT_RATE_WINDOW - 60  # oldest entry is 60 s ago

    mocker.patch("app.v2.reports.post_reports.time", return_value=fixed_now)
    mock_limiter = mocker.patch("app.v2.reports.post_reports._get_report_limiter")
    mock_scoped = mock_limiter.return_value.for_scope.return_value
    mock_scoped.acquire_lease.return_value = (False, seconds_to_wait)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email", "language": "en"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 429
    data = json.loads(response.get_data(as_text=True))
    assert data["errors"][0]["error"] == "RateLimitExceeded"
    assert data["errors"][0]["message"] == f"Maximum {REPORT_RATE_LIMIT} report requests per hour"
    assert response.headers["X-RateLimit-Limit"] == str(REPORT_RATE_LIMIT)
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert int(response.headers["X-RateLimit-Reset"]) == math.ceil(fixed_now + seconds_to_wait)
    assert int(response.headers["Retry-After"]) > 0
    mock_limiter.return_value.for_scope.assert_called_once_with(str(sample_service.id))
    mock_scoped.acquire_lease.assert_called_once_with()


def test_post_report_rate_limit_not_triggered_below_limit(
    client, sample_service, mocker, create_api_key_with_manage_reports_perm
):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    mock_limiter = mocker.patch("app.v2.reports.post_reports._get_report_limiter")
    mock_limiter.return_value.for_scope.return_value.acquire_lease.return_value = (True, 0)

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email", "language": "en"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 202


def test_post_report_rate_limit_skipped_when_redis_disabled(
    client, sample_service, mocker, create_api_key_with_manage_reports_perm, notify_api
):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    mock_limiter = mocker.patch("app.v2.reports.post_reports._get_report_limiter")

    mocker.patch.dict(notify_api.config, {"REDIS_ENABLED": False})
    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email", "language": "en"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 202
    mock_limiter.assert_not_called()


def test_post_report_requires_authentication(client):
    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email"}),
        headers=[("Content-Type", "application/json")],
    )

    assert response.status_code == 401
