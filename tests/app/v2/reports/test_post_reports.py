import json
import math

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


def test_post_report_rate_limit_returns_429(client, sample_service, mocker, create_api_key_with_manage_reports_perm):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    fixed_now = 1_700_000_000.0

    mocker.patch("app.v2.reports.post_reports.time", return_value=fixed_now)

    # Simulate 10 existing entries in the sliding window (pipeline returns [None, 10])
    mock_pipeline = mocker.MagicMock()
    mock_pipeline.execute.return_value = [None, 10]
    mocker.patch("app.v2.reports.post_reports.redis_store.redis_store.pipeline", return_value=mock_pipeline)
    # Oldest entry is 60 seconds ago; reset = oldest + 3600
    oldest_ts = fixed_now - 60
    mocker.patch(
        "app.v2.reports.post_reports.redis_store.redis_store.zrange",
        return_value=[(b"entry", oldest_ts)],
    )

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email", "language": "en"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 429
    data = json.loads(response.get_data(as_text=True))
    assert data["errors"][0]["error"] == "RateLimitExceeded"
    assert data["errors"][0]["message"] == "Maximum 10 report requests per hour"
    assert response.headers["X-RateLimit-Limit"] == "10"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert int(response.headers["X-RateLimit-Reset"]) == math.ceil(oldest_ts + 3600)
    assert int(response.headers["Retry-After"]) > 0


def test_post_report_rate_limit_not_triggered_below_limit(
    client, sample_service, mocker, create_api_key_with_manage_reports_perm
):
    mocker.patch("app.v2.reports.post_reports.generate_report.apply_async")
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    fixed_now = 1_700_000_000.0
    mocker.patch("app.v2.reports.post_reports.time", return_value=fixed_now)

    # Simulate 9 existing entries (under the 10-per-hour limit)
    mock_pipeline = mocker.MagicMock()
    mock_pipeline.execute.return_value = [None, 9]
    mock_pipeline2 = mocker.MagicMock()
    mock_pipeline2.execute.return_value = [1, True]
    mocker.patch(
        "app.v2.reports.post_reports.redis_store.redis_store.pipeline",
        side_effect=[mock_pipeline, mock_pipeline2],
    )

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
    mock_pipeline = mocker.patch("app.v2.reports.post_reports.redis_store.redis_store.pipeline")

    with notify_api.test_request_context():
        notify_api.config["REDIS_ENABLED"] = False

    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email", "language": "en"}),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 202
    mock_pipeline.assert_not_called()


def test_post_report_requires_authentication(client):
    response = client.post(
        path="/v2/reports",
        data=json.dumps({"report_type": "email"}),
        headers=[("Content-Type", "application/json")],
    )

    assert response.status_code == 401
