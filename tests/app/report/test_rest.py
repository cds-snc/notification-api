import uuid

from app.models import ReportStatus, ReportType


def test_create_report_succeeds_with_valid_data(admin_request, sample_service, sample_user):
    """Test that creating a report with valid data succeeds"""
    data = {"report_type": ReportType.EMAIL.value, "requesting_user_id": str(sample_user.id)}

    response = admin_request.post("report.create_service_report", service_id=sample_service.id, _data=data, _expected_status=201)

    assert response["data"]["report_type"] == ReportType.EMAIL.value
    assert response["data"]["service_id"] == str(sample_service.id)
    assert response["data"]["status"] == ReportStatus.REQUESTED.value
    assert "id" in response["data"]
    assert "requested_at" in response["data"]


def test_create_report_with_invalid_report_type(admin_request, sample_service):
    """Test that creating a report with an invalid report_type returns 400"""
    data = {"report_type": "invalid_type"}

    response = admin_request.post("report.create_service_report", service_id=sample_service.id, _data=data, _expected_status=400)

    assert response["result"] == "error"
    assert "Invalid report type" in response["message"]


def test_create_report_for_nonexistent_service(admin_request):
    """Test that creating a report for a nonexistent service returns an error"""
    data = {"report_type": ReportType.SMS.value}

    admin_request.post("report.create_service_report", service_id=uuid.uuid4(), _data=data, _expected_status=404)
