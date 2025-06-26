import csv
import io
from datetime import datetime, timedelta
from unittest.mock import patch

from app.report.utils import (
    Translate,
    build_notifications_query,
    generate_csv_from_notifications,
    send_requested_report_ready,
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
        notification_statuses = ["delivered", "failed"]
        job_id = "job-id-1"
        # When
        with patch("app.report.utils.build_notifications_query") as mock_build_query:
            with patch("app.report.utils.compile_query_for_copy") as mock_compile_query:
                with patch("app.report.utils.stream_query_to_s3") as mock_stream:
                    mock_build_query.return_value = "mock query"
                    mock_compile_query.return_value = "mock copy command"

                    # Call the function
                    generate_csv_from_notifications(
                        service_id, notification_type, language, notification_statuses, job_id, days_limit, s3_bucket, s3_key
                    )

                    # Then
                    mock_build_query.assert_called_once_with(
                        service_id=service_id,
                        notification_type=notification_type,
                        language=language,
                        notification_statuses=notification_statuses,
                        job_id=job_id,
                        days_limit=days_limit,
                    )
                    mock_compile_query.assert_called_once_with("mock query")
                    mock_stream.assert_called_once_with("mock copy command", s3_bucket, s3_key)

    def test_build_notifications_query_with_status_filter(self):
        # Given
        service_id = "service-id-1"
        notification_type = "email"
        language = "en"
        notification_statuses = ["delivered", "failed"]

        # When
        query = build_notifications_query(
            service_id=service_id,
            notification_type=notification_type,
            language=language,
            notification_statuses=notification_statuses,
        )

        # Then
        # Convert query to string to check the SQL
        sql_str = str(query.statement.compile(compile_kwargs={"literal_binds": True}))
        assert "notification_status IN (" in sql_str
        substituted_statuses = [
            "provider-failure",
            "validation-failed",
            "returned-letter",
            "technical-failure",
            "delivered",
            "failed",
            "pii-check-failed",
            "temporary-failure",
            "permanent-failure",
            "virus-scan-failed",
        ]
        for status in substituted_statuses:
            assert status in sql_str

    def test_build_notifications_query_with_empty_status_filter(self):
        # Given
        service_id = "service-id-1"
        notification_type = "email"
        language = "en"
        notification_statuses = []

        # When
        query = build_notifications_query(
            service_id=service_id,
            notification_type=notification_type,
            language=language,
            notification_statuses=notification_statuses,
        )

        # Then
        sql_str = str(query.statement.compile(compile_kwargs={"literal_binds": True}))
        assert "notification.status IN" not in sql_str  # No status filter should be applied

    def test_build_notifications_query_with_job_id_filter(self):
        # Given
        service_id = "service-id-1"
        notification_type = "email"
        language = "en"
        job_id = "job-id-1"

        # When
        query = build_notifications_query(
            service_id=service_id,
            notification_type=notification_type,
            language=language,
            job_id=job_id,
        )

        # Then
        # Convert query to string to check the SQL
        sql_str = str(query.statement.compile(compile_kwargs={"literal_binds": True}))
        assert f".job_id = '{job_id}'" in sql_str


class TestEmails:
    def test_send_email_notification2(self, mocker, sample_template, sample_report, sample_service, sample_notification):
        send_notification_mock = mocker.patch("app.report.utils.send_notification_to_queue")
        mocker.patch("app.report.utils.dao_get_template_by_id", return_value=sample_template)
        service_query_mock = mocker.patch("app.report.utils.Service.query")
        service_query_mock.get.side_effect = lambda service_id: sample_service
        mocker.patch("app.report.utils.persist_notification", return_value=sample_notification)
        send_requested_report_ready(sample_report)
        send_notification_mock.assert_called_once_with(sample_notification, False, queue="notify-internal-tasks")


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
            query = build_notifications_query(service_id=str(service.id), notification_type="email", language="en", days_limit=7)
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
                job_id=None,
                s3_bucket="test-bucket",
                s3_key="test-key.csv",
            )

        # Check the buffer content
        rows = list(csv.DictReader(csv_buffer.getvalue().splitlines()))
        assert len(rows) == 2
        assert rows[0]["Recipient"] == "user1@example.com"
        assert rows[1]["Recipient"] == "user2@example.com"
        assert set(r["Status"] for r in rows) == {"Delivered", "Failed"}

    def test_generate_csv_from_notifications_with_status_filter(self, notify_db, notify_db_session, sample_user):
        service = create_sample_service(notify_db, notify_db_session, user=sample_user)
        template = create_sample_email_template(notify_db, notify_db_session, service=service)

        now = datetime.utcnow()
        notification_data = [
            {"to_field": "user1@example.com", "status": "delivered", "personalisation": {"name": "User1"}, "created_at": now},
            {"to_field": "user2@example.com", "status": "failed", "personalisation": {"name": "User2"}, "created_at": now},
            {"to_field": "user3@example.com", "status": "sending", "personalisation": {"name": "User3"}, "created_at": now},
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

        csv_buffer = io.StringIO()

        def fake_stream_query_to_s3(copy_command, s3_bucket, s3_key):
            query = build_notifications_query(
                service_id=str(service.id),
                notification_type="email",
                language="en",
                notification_statuses=["delivered", "failed"],
            )
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
                notification_statuses=["delivered", "failed"],
                job_id=None,
                days_limit=7,
                s3_bucket="test-bucket",
                s3_key="test-key.csv",
            )

        rows = list(csv.DictReader(csv_buffer.getvalue().splitlines()))
        assert len(rows) == 2  # Only delivered and failed notifications
        assert set(r["Recipient"] for r in rows) == {"user1@example.com", "user2@example.com"}
        assert set(r["Status"] for r in rows) == {"Delivered", "Failed"}
