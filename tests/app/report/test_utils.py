from app.report.utils import (
    CSV_FIELDNAMES,
    _l,
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

    # Create expected CSV content
    header = ",".join(CSV_FIELDNAMES) + "\n"
    row1 = "test1@example.com,Template 1,email,User 1,user1@example.com,Job 1,delivered,2023-01-01 12:00:00\n"
    row2 = "test2@example.com,Template 2,sms,User 2,user2@example.com,Job 2,failed,2023-01-02 12:00:00\n"
    expected = "\ufeff" + header + row1 + row2

    assert result == expected.encode("utf-8")


def test_get_csv_file_data_empty_list():
    """Test get_csv_file_data with empty list"""
    result = get_csv_file_data([])

    # Create expected CSV content - just the header
    header = ",".join(CSV_FIELDNAMES) + "\n"
    expected = "\ufeff" + header

    assert result == expected.encode("utf-8")
