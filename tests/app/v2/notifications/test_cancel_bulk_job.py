from datetime import datetime, timedelta

from tests import create_authorization_header
from tests.app.db import create_job, create_service, create_template


def _get_headers(service_id):
    return [create_authorization_header(service_id=service_id)]


def test_cancel_bulk_job_cancels_scheduled_job(client, sample_template):
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


def test_cancel_bulk_job_returns_404_for_unknown_job(client, sample_service):
    response = client.delete(
        "/v2/notifications/bulk/201b64f0-0a3a-404b-96d4-d4a0f0d0c3bd",
        headers=_get_headers(sample_service.id),
    )

    assert response.status_code == 404
    assert response.get_json() == {
        "status_code": 404,
        "errors": [{"error": "JobNotFoundError", "message": "Job not found in database"}],
    }


def test_cancel_bulk_job_returns_409_for_job_that_already_started(client, sample_template):
    job = create_job(sample_template, job_status="in progress", processing_started=datetime.utcnow())

    response = client.delete(f"/v2/notifications/bulk/{job.id}", headers=_get_headers(sample_template.service_id))

    assert response.status_code == 409
    assert response.get_json() == {
        "status_code": 409,
        "errors": [
            {
                "error": "JobCancellationNotAllowedError",
                "message": "Job cannot be cancelled because it is already being sent or has already been sent",
            }
        ],
    }


def test_cancel_bulk_job_returns_409_for_job_that_already_finished(client, sample_template):
    job = create_job(sample_template, job_status="finished")

    response = client.delete(f"/v2/notifications/bulk/{job.id}", headers=_get_headers(sample_template.service_id))

    assert response.status_code == 409


def test_cancel_bulk_job_returns_409_for_scheduled_job_whose_time_has_passed(client, sample_template):
    job = create_job(
        sample_template,
        job_status="scheduled",
        scheduled_for=(datetime.utcnow() - timedelta(minutes=1)).isoformat(),
    )

    response = client.delete(f"/v2/notifications/bulk/{job.id}", headers=_get_headers(sample_template.service_id))

    assert response.status_code == 409


def test_cancel_bulk_job_returns_404_for_job_belonging_to_another_service(client, sample_template):
    other_service = create_service(service_name="Other service")
    other_template = create_template(service=other_service)
    job = create_job(
        other_template,
        job_status="scheduled",
        scheduled_for=(datetime.utcnow() + timedelta(hours=1)).isoformat(),
    )

    response = client.delete(f"/v2/notifications/bulk/{job.id}", headers=_get_headers(sample_template.service_id))

    assert response.status_code == 404
