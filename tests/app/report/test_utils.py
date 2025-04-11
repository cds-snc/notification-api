from unittest.mock import patch

from app.report.utils import (
    CSV_FIELDNAMES,
    _l,
    generate_csv_from_notifications,
    get_csv_file_data,
    serialized_notification_to_csv,
)


def test_mock_translate_function():
    """Test the mock translation function behaves as expected"""
    assert _l("Test") == "Test"
    assert _l("Status") == "Status"


def test_serialized_notification_to_csv_with_en_language():
    """Test serialized_notification_to_csv with English language"""
    test_notification = {
        "recipient": "test@example.com",
        "template_name": "Test Template",
        "template_type": "email",
        "created_by_name": "Test User",
        "created_by_email_address": "user@example.com",
        "job_name": "Test Job",
        "status": "delivered",
        "created_at": "2023-01-01 12:00:00",
    }

    result = serialized_notification_to_csv(test_notification, lang="en")
    expected = "test@example.com,Test Template,email,Test User,user@example.com,Test Job,delivered,2023-01-01 12:00:00\n"
    assert result == expected


def test_serialized_notification_to_csv_with_empty_fields():
    """Test serialized_notification_to_csv with empty fields"""
    test_notification = {
        "recipient": "test@example.com",
        "template_name": "Test Template",
        "template_type": "email",
        "created_by_name": None,
        "created_by_email_address": None,
        "job_name": None,
        "status": "delivered",
        "created_at": "2023-01-01 12:00:00",
    }

    result = serialized_notification_to_csv(test_notification)
    expected = "test@example.com,Test Template,email,,,,delivered,2023-01-01 12:00:00\n"
    assert result == expected


def test_get_csv_file_data():
    """Test get_csv_file_data generates correct CSV file"""
    test_notifications = [
        {
            "recipient": "test1@example.com",
            "template_name": "Template 1",
            "template_type": "email",
            "created_by_name": "User 1",
            "created_by_email_address": "user1@example.com",
            "job_name": "Job 1",
            "status": "delivered",
            "created_at": "2023-01-01 12:00:00",
        },
        {
            "recipient": "test2@example.com",
            "template_name": "Template 2",
            "template_type": "sms",
            "created_by_name": "User 2",
            "created_by_email_address": "user2@example.com",
            "job_name": "Job 2",
            "status": "failed",
            "created_at": "2023-01-02 12:00:00",
        },
    ]

    result = get_csv_file_data(test_notifications)

    # Check for UTF-8 encoding
    assert isinstance(result, bytes)
    result_str = result.decode("utf-8")

    # Check for BOM
    assert result_str.startswith("\ufeff")

    # Check CSV content
    lines = result_str.strip().split("\n")
    assert len(lines) == 3  # Header + 2 rows

    # Check header
    header = lines[0]
    for field in CSV_FIELDNAMES:
        assert field in header

    # Check data rows
    assert "test1@example.com" in lines[1]
    assert "test2@example.com" in lines[2]
    assert "Template 1" in lines[1]
    assert "Template 2" in lines[2]


def test_get_csv_file_data_empty_list():
    """Test get_csv_file_data with empty list"""
    result = get_csv_file_data([])

    # Check for UTF-8 encoding
    assert isinstance(result, bytes)
    result_str = result.decode("utf-8")

    # Check for BOM
    assert result_str.startswith("\ufeff")

    # Check CSV content
    lines = result_str.strip().split("\n")
    assert len(lines) == 1  # Only header

    # Check header
    header = lines[0]
    for field in CSV_FIELDNAMES:
        assert field in header


class TestGenerateCsvFromNotifications:
    def test_calls_helper_functions_with_correct_parameters(self):
        # Given
        service_id = "service-id-1"
        notification_type = "email"
        days_limit = 14
        s3_bucket = "test-bucket"
        s3_key = "test-key.csv"

        # When
        with patch("app.report.utils.build_notifications_query") as mock_build_query:
            with patch("app.report.utils.compile_query_for_copy") as mock_compile_query:
                with patch("app.report.utils.stream_query_to_s3") as mock_stream:
                    mock_build_query.return_value = "mock query"
                    mock_compile_query.return_value = "mock copy command"

                    # Call the function
                    generate_csv_from_notifications(service_id, notification_type, days_limit, s3_bucket, s3_key)

                    # Then
                    mock_build_query.assert_called_once_with(service_id, notification_type, days_limit)
                    mock_compile_query.assert_called_once_with("mock query")
                    mock_stream.assert_called_once_with("mock copy command", s3_bucket, s3_key)
