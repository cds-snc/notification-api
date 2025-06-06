import uuid

from app.models import ReportStatus, ReportType


def test_create_report_succeeds_with_valid_data(mocker, admin_request, sample_service, sample_user):
    """Test that creating a report with valid data succeeds"""
    # Mock the generate_report Celery task to avoid actual task execution
    generate_report_mock = mocker.patch("app.report.rest.generate_report.apply_async")

    # Use actual database operations instead of mocking create_report
    data = {"report_type": ReportType.EMAIL.value, "requesting_user_id": str(sample_user.id), "language": "en"}

    # Call the endpoint which will create a real report in the database
    response = admin_request.post("report.create_service_report", service_id=sample_service.id, _data=data, _expected_status=201)

    # Verify response contains expected data
    assert response["data"]["report_type"] == ReportType.EMAIL.value
    assert response["data"]["service_id"] == str(sample_service.id)
    assert response["data"]["language"] == "en"
    assert response["data"]["status"] == ReportStatus.REQUESTED.value

    # Extract the report ID from the response
    report_id = response["data"]["id"]

    # Verify generate_report was called with correct parameters
    generate_report_mock.assert_called_once()
    assert str(generate_report_mock.call_args[0][0][0]) == report_id
    assert generate_report_mock.call_args[0][0][1] == []  # Empty notification_statuses
    assert generate_report_mock.call_args[1]["queue"] == "generate-reports"


def test_create_report_succeeds_with_notification_statuses(mocker, admin_request, sample_service, sample_user):
    """Test that creating a report with notification_statuses passes the data to generate_report task"""
    # Mock the generate_report Celery task to avoid actual task execution
    generate_report_mock = mocker.patch("app.report.rest.generate_report.apply_async")

    notification_statuses = ["delivered", "sending"]
    data = {
        "report_type": ReportType.EMAIL.value,
        "requesting_user_id": str(sample_user.id),
        "notification_statuses": notification_statuses,
        "language": "en",
    }

    # Call the endpoint which will create a real report in the database
    response = admin_request.post("report.create_service_report", service_id=sample_service.id, _data=data, _expected_status=201)

    # Verify response contains expected data
    assert response["data"]["report_type"] == ReportType.EMAIL.value
    assert str(response["data"]["service_id"]) == str(sample_service.id)
    assert response["data"]["language"] == "en"
    assert response["data"]["status"] == ReportStatus.REQUESTED.value

    # Extract the report ID from the response
    report_id = response["data"]["id"]

    # Verify generate_report was called with notification_statuses
    generate_report_mock.assert_called_once()
    assert str(generate_report_mock.call_args[0][0][0]) == report_id
    assert generate_report_mock.call_args[0][0][1] == notification_statuses
    assert generate_report_mock.call_args[1]["queue"] == "generate-reports"


def test_create_report_succeeds_with_job_id(mocker, admin_request, sample_service, sample_user, sample_job):
    """Test that creating a report with job_id passes the data to generate_report task"""
    # Mock the generate_report Celery task to avoid actual task execution
    generate_report_mock = mocker.patch("app.report.rest.generate_report.apply_async")

    data = {
        "report_type": ReportType.SMS.value,
        "requesting_user_id": str(sample_user.id),
        "job_id": str(sample_job.id),
        "language": "en",
    }

    # Call the endpoint which will create a real report in the database
    response = admin_request.post("report.create_service_report", service_id=sample_service.id, _data=data, _expected_status=201)

    # Verify response contains expected data
    assert response["data"]["report_type"] == ReportType.SMS.value
    assert str(response["data"]["service_id"]) == str(sample_service.id)
    assert response["data"]["job_id"] == str(sample_job.id)
    assert response["data"]["language"] == "en"
    assert response["data"]["status"] == ReportStatus.REQUESTED.value

    # Extract the report ID from the response
    report_id = response["data"]["id"]

    # Verify generate_report was called with empty notification_statuses
    generate_report_mock.assert_called_once()
    assert str(generate_report_mock.call_args[0][0][0]) == report_id
    assert generate_report_mock.call_args[0][0][1] == []  # Empty notification_statuses
    assert generate_report_mock.call_args[1]["queue"] == "generate-reports"


def test_create_report_succeeds_with_both_notification_statuses_and_job_id(
    mocker, admin_request, sample_service, sample_user, sample_job
):
    """Test that creating a report with both notification_statuses and job_id passes both parameters correctly"""
    # Mock the generate_report Celery task to avoid actual task execution
    generate_report_mock = mocker.patch("app.report.rest.generate_report.apply_async")

    notification_statuses = ["delivered", "failed"]
    data = {
        "report_type": ReportType.EMAIL.value,
        "requesting_user_id": str(sample_user.id),
        "job_id": str(sample_job.id),
        "notification_statuses": notification_statuses,
        "language": "en",
    }

    # Call the endpoint which will create a real report in the database
    response = admin_request.post("report.create_service_report", service_id=sample_service.id, _data=data, _expected_status=201)

    # Verify response contains expected data
    assert response["data"]["report_type"] == ReportType.EMAIL.value
    assert response["data"]["service_id"] == str(sample_service.id)
    assert response["data"]["job_id"] == str(sample_job.id)
    assert response["data"]["language"] == "en"
    assert response["data"]["status"] == ReportStatus.REQUESTED.value

    # Extract the report ID from the response
    report_id = response["data"]["id"]

    # Verify generate_report was called with notification_statuses
    generate_report_mock.assert_called_once()
    assert str(generate_report_mock.call_args[0][0][0]) == report_id
    assert generate_report_mock.call_args[0][0][1] == notification_statuses
    assert generate_report_mock.call_args[1]["queue"] == "generate-reports"


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


def test_get_service_reports_returns_reports_with_default_limit(admin_request, sample_service, mocker):
    """Test that getting reports for a service with default limit succeeds"""
    mock_reports = [
        {
            "id": uuid.uuid4(),
            "report_type": ReportType.EMAIL.value,
            "service_id": sample_service.id,
            "status": ReportStatus.REQUESTED.value,
        }
    ]
    mock_get_reports = mocker.patch("app.report.rest.get_reports_for_service", return_value=mock_reports)

    response = admin_request.get("report.get_service_reports", service_id=sample_service.id)

    assert response["data"]
    # Verify the default limit of 7 days was used
    mock_get_reports.assert_called_once_with(sample_service.id, 7)


def test_get_service_reports_with_custom_days_limit(admin_request, sample_service, mocker):
    """Test that getting reports with a custom days limit succeeds"""
    mock_reports = [
        {
            "id": uuid.uuid4(),
            "report_type": ReportType.SMS.value,
            "service_id": sample_service.id,
            "status": ReportStatus.REQUESTED.value,
        }
    ]
    mock_get_reports = mocker.patch("app.report.rest.get_reports_for_service", return_value=mock_reports)

    custom_days = 7
    response = admin_request.get("report.get_service_reports", service_id=sample_service.id, limit_days=custom_days)

    assert response["data"]
    # Verify the custom limit was used
    mock_get_reports.assert_called_once_with(sample_service.id, custom_days)


def test_get_service_reports_for_nonexistent_service(admin_request):
    """Test that getting reports for a nonexistent service returns a 404 error"""
    admin_request.get("report.get_service_reports", service_id=uuid.uuid4(), _expected_status=404)


def test_get_service_reports_returns_empty_list_when_no_reports(admin_request, sample_service, mocker):
    """Test that endpoint returns empty list when no reports exist for service"""
    mock_get_reports = mocker.patch("app.report.rest.get_reports_for_service", return_value=[])

    response = admin_request.get("report.get_service_reports", service_id=sample_service.id)

    assert response["data"] == []
    mock_get_reports.assert_called_once()
