from datetime import date, datetime

from freezegun import freeze_time

from tests import create_authorization_header
from tests.app.db import (
    create_ft_notification_status,
    create_job,
    create_notification,
    create_service,
    create_template,
    save_notification,
)


def _get_headers(service_id):
    return [create_authorization_header(service_id=service_id)]


@freeze_time("2026-08-18")
def test_get_bulk_job_returns_job_with_recent_statistics(client, sample_template):
    job = create_job(sample_template, processing_started=datetime(2026, 8, 18))
    save_notification(create_notification(template=sample_template, job=job, status="sending"))

    response = client.get(f"/v2/notifications/bulk/{job.id}", headers=_get_headers(sample_template.service_id))

    assert response.status_code == 200
    assert response.get_json()["data"]["id"] == str(job.id)
    assert response.get_json()["data"]["statistics"] == [{"status": "sending", "count": 1}]


@freeze_time("2026-08-18")
def test_get_bulk_job_returns_archived_job_with_old_statistics(client, sample_template):
    job = create_job(sample_template, processing_started=datetime(2026, 8, 5), archived=True)
    create_ft_notification_status(
        date(2026, 8, 5),
        template=sample_template,
        job=job,
        notification_status="temporary-failure",
    )

    response = client.get(f"/v2/notifications/bulk/{job.id}", headers=_get_headers(sample_template.service_id))

    assert response.status_code == 200
    assert response.get_json()["data"]["archived"] is True
    assert response.get_json()["data"]["statistics"] == [{"status": "temporary-failure", "count": 1}]


def test_get_bulk_job_returns_404_for_unknown_job(client, sample_service):
    response = client.get(
        "/v2/notifications/bulk/201b64f0-0a3a-404b-96d4-d4a0f0d0c3bd",
        headers=_get_headers(sample_service.id),
    )

    assert response.status_code == 404
    assert response.get_json() == {
        "status_code": 404,
        "errors": [{"error": "JobNotFoundError", "message": "Job not found in database"}],
    }


def test_get_bulk_jobs_returns_only_jobs_for_authenticated_service(client, sample_template):
    job = create_job(sample_template)
    other_service = create_service(service_name="Other service")
    other_template = create_template(service=other_service)
    other_job = create_job(other_template)

    response = client.get("/v2/notifications/bulk", headers=_get_headers(sample_template.service_id))

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.get_json()["bulk_jobs"]}
    assert str(job.id) in returned_ids
    assert str(other_job.id) not in returned_ids


def test_get_bulk_jobs_supports_cursor_pagination(client, sample_template, monkeypatch):
    first_job = create_job(sample_template, created_at=datetime(2026, 8, 18, 12, 0))
    second_job = create_job(sample_template, created_at=datetime(2026, 8, 18, 11, 0))
    monkeypatch.setitem(client.application.config, "API_PAGE_SIZE", 1)

    first_response = client.get("/v2/notifications/bulk", headers=_get_headers(sample_template.service_id))
    first_page = first_response.get_json()

    second_response = client.get(
        "/v2/notifications/bulk",
        query_string={"older_than": first_page["bulk_jobs"][0]["id"]},
        headers=_get_headers(sample_template.service_id),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_page["bulk_jobs"][0]["id"] == str(first_job.id)
    assert second_response.get_json()["bulk_jobs"][0]["id"] == str(second_job.id)
    assert first_page["links"]["next"]


def test_get_bulk_jobs_rejects_cursor_from_another_service(client, sample_template):
    other_service = create_service(service_name="Other service")
    other_template = create_template(service=other_service)
    other_job = create_job(other_template)

    response = client.get(
        "/v2/notifications/bulk",
        query_string={"older_than": str(other_job.id)},
        headers=_get_headers(sample_template.service_id),
    )

    assert response.status_code == 400


def test_get_bulk_jobs_rejects_unknown_cursor(client, sample_service):
    response = client.get(
        "/v2/notifications/bulk",
        query_string={"older_than": "201b64f0-0a3a-404b-96d4-d4a0f0d0c3bd"},
        headers=_get_headers(sample_service.id),
    )

    assert response.status_code == 400
