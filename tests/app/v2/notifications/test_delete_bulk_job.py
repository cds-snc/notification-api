from datetime import datetime, timedelta

from tests import create_authorization_header
from tests.app.db import create_job, create_service, create_template


def _get_headers(service_id):
    return [create_authorization_header(service_id=service_id)]


def test_delete_bulk_job_cancels_scheduled_job(client, sample_template):
    job = create_job(
        sample_template,
        notification_count=5,
        job_status="scheduled",
        scheduled_for=(datetime.utcnow() + timedelta(hours=1)).isoformat(),
    )

    response = client.delete(f"/v2/notifications/bulk/{job.id}", headers=_get_headers(sample_template.service_id))

    assert response.status_code == 200
    assert response.get_json()["data"]["id"] == str(job.id)
    assert response.get_json()["data"]["job_status"] == "cancelled"


def test_delete_bulk_job_returns_404_for_unknown_job(client, sample_service):
    response = client.delete(
        "/v2/notifications/bulk/201b64f0-0a3a-404b-96d4-d4a0f0d0c3bd",
        headers=_get_headers(sample_service.id),
    )

    assert response.status_code == 404
    assert response.get_json() == {
        "status_code": 404,
        "errors": [{"error": "JobNotFoundError", "message": "Job not found in database"}],
    }


def test_delete_bulk_job_returns_404_for_job_that_already_started(client, sample_template):
    job = create_job(sample_template, job_status="in progress", processing_started=datetime.utcnow())

    response = client.delete(f"/v2/notifications/bulk/{job.id}", headers=_get_headers(sample_template.service_id))

    assert response.status_code == 404


def test_delete_bulk_job_returns_404_for_job_belonging_to_another_service(client, sample_template):
    other_service = create_service(service_name="Other service")
    other_template = create_template(service=other_service)
    job = create_job(
        other_template,
        job_status="scheduled",
        scheduled_for=(datetime.utcnow() + timedelta(hours=1)).isoformat(),
    )

    response = client.delete(f"/v2/notifications/bulk/{job.id}", headers=_get_headers(sample_template.service_id))

    assert response.status_code == 404
