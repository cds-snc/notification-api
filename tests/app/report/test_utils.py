from unittest.mock import patch

from app.report.utils import (
    _l,
    generate_csv_from_notifications,
)


def test_mock_translate_function():
    """Test the mock translation function behaves as expected"""
    assert _l("Test") == "Test"
    assert _l("Status") == "Status"


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
