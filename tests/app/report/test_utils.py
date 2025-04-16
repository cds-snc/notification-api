from unittest.mock import patch

from app.report.utils import (
    Translate,
    generate_csv_from_notifications,
    send_requested_report_ready,
)


def test_translate_en():
    translate = Translate(language="en").translate
    assert translate("Recipient") == "Recipient"
    assert translate("Nonexistent") == "Nonexistent"


def test_translate_french_language():
    translate = Translate(language="fr").translate
    assert translate("Recipient") == "Destinataire"
    assert translate("Template") == "Gabarit"
    assert translate("Nonexistent") == "Nonexistent"


class TestGenerateCsvFromNotifications:
    def test_calls_helper_functions_with_correct_parameters(self):
        # Given
        service_id = "service-id-1"
        notification_type = "email"
        days_limit = 14
        s3_bucket = "test-bucket"
        s3_key = "test-key.csv"
        language = "en"
        # When
        with patch("app.report.utils.build_notifications_query") as mock_build_query:
            with patch("app.report.utils.compile_query_for_copy") as mock_compile_query:
                with patch("app.report.utils.stream_query_to_s3") as mock_stream:
                    mock_build_query.return_value = "mock query"
                    mock_compile_query.return_value = "mock copy command"

                    # Call the function
                    generate_csv_from_notifications(service_id, notification_type, language, days_limit, s3_bucket, s3_key)

                    # Then
                    mock_build_query.assert_called_once_with(service_id, notification_type, language, days_limit)
                    mock_compile_query.assert_called_once_with("mock query")
                    mock_stream.assert_called_once_with("mock copy command", s3_bucket, s3_key)


class TestEmails:
    def test_send_email_notification2(self, mocker, sample_template, sample_report, sample_service, sample_notification):
        send_notification_mock = mocker.patch("app.report.utils.send_notification_to_queue")
        mocker.patch("app.report.utils.dao_get_template_by_id", return_value=sample_template)
        service_query_mock = mocker.patch("app.report.utils.Service.query")
        service_query_mock.get.side_effect = lambda service_id: sample_service
        mocker.patch("app.report.utils.persist_notification", return_value=sample_notification)
        send_requested_report_ready(sample_report)
        send_notification_mock.assert_called_once_with(sample_notification, False, queue="notify-internal-tasks")
