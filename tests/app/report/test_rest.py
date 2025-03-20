import json
import uuid

from flask import url_for

from app.models import ReportStatus, ReportType


def test_create_report_succeeds_with_valid_data(client, sample_service):
    """Test that creating a report with valid data succeeds"""
    data = {"report_type": ReportType.EMAIL.value, "requesting_user_id": str(uuid.uuid4())}

    response = client.post(
        url_for("report.create_service_report", service_id=sample_service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json")],
    )

    assert response.status_code == 201

    json_resp = json.loads(response.get_data(as_text=True))

    assert json_resp["data"]["report_type"] == ReportType.EMAIL.value
    assert json_resp["data"]["service_id"] == str(sample_service.id)
    assert json_resp["data"]["status"] == ReportStatus.REQUESTED.value
    assert "id" in json_resp["data"]
    assert "requested_at" in json_resp["data"]


def test_create_report_with_invalid_report_type(client, sample_service):
    """Test that creating a report with an invalid report_type returns 400"""
    data = {"report_type": "invalid_type"}

    response = client.post(
        url_for("report.create_service_report", service_id=sample_service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json")],
    )

    assert response.status_code == 400

    json_resp = json.loads(response.get_data(as_text=True))
    assert json_resp["result"] == "error"
    assert "Invalid report type" in json_resp["message"]


def test_create_report_for_nonexistent_service(client):
    """Test that creating a report for a nonexistent service returns an error"""
    data = {"report_type": ReportType.SMS.value}

    response = client.post(
        url_for("report.create_service_report", service_id=uuid.uuid4()),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json")],
    )

    assert response.status_code == 404


def test_create_report_creates_db_entry(client, sample_service, mocker):
    """Test that creating a report creates a database entry with correct values"""
    mock_create_report = mocker.patch("app.report.rest.create_report")

    data = {"report_type": ReportType.JOB.value, "requesting_user_id": str(uuid.uuid4())}

    response = client.post(
        url_for("report.create_service_report", service_id=sample_service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json")],
    )

    assert response.status_code == 201

    # Verify create_report was called with the expected parameters
    assert mock_create_report.called
    report = mock_create_report.call_args[0][0]
    assert report.report_type == ReportType.JOB.value
    assert report.service_id == sample_service.id
    assert report.status == ReportStatus.REQUESTED.value
    assert str(report.requesting_user_id) == data["requesting_user_id"]
