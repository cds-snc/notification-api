import csv
import io
from datetime import datetime, timedelta
from unittest.mock import patch

from app.report.utils import (
    Translate,
    build_notifications_query,
    generate_csv_from_notifications,
)
from tests.app.conftest import create_sample_email_template, create_sample_notification, create_sample_service


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


class TestNotificationReportIntegration:
    def test_generate_csv_from_notifications_integration(self, notify_db, notify_db_session, sample_user):
        service = create_sample_service(notify_db, notify_db_session, user=sample_user)
        template = create_sample_email_template(notify_db, notify_db_session, service=service)

        now = datetime.utcnow()
        notification_data = [
            {"to_field": "user1@example.com", "status": "delivered", "personalisation": {"name": "User1"}, "created_at": now},
            {
                "to_field": "user2@example.com",
                "status": "failed",
                "personalisation": {"name": "User2"},
                "created_at": now - timedelta(minutes=1),
            },
        ]
        for data in notification_data:
            create_sample_notification(
                notify_db,
                notify_db_session,
                service=service,
                template=template,
                to_field=data["to_field"],
                status=data["status"],
                personalisation=data["personalisation"],
                created_at=data["created_at"],
            )

        # Patch stream_query_to_s3 to write to a buffer instead of S3
        csv_buffer = io.StringIO()

        def fake_stream_query_to_s3(copy_command, s3_bucket, s3_key):
            # Actually run the query and write CSV to the buffer
            query = build_notifications_query(str(service.id), "email", "en", 7)
            result = query.all()
            fieldnames = [col["name"] for col in query.column_descriptions]
            writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
            writer.writeheader()
            for row in result:
                writer.writerow(dict(zip(fieldnames, row)))
            csv_buffer.seek(0)

        with patch("app.report.utils.stream_query_to_s3", fake_stream_query_to_s3):
            generate_csv_from_notifications(
                str(service.id),
                "email",
                "en",
                days_limit=7,
                s3_bucket="test-bucket",
                s3_key="test-key.csv",
            )

        # Check the buffer content
        rows = list(csv.DictReader(csv_buffer.getvalue().splitlines()))
        assert len(rows) == 2
        assert rows[0]["Recipient"] == "user1@example.com"
        assert rows[1]["Recipient"] == "user2@example.com"
        assert set(r["Status"] for r in rows) == {"Delivered", "Failed"}
