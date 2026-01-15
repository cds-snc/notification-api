import json
from unittest.mock import Mock, patch

from app.clients.email.aws_ses import AwsSesClientException
from tests import create_authorization_header
from tests.app.db import create_notification, create_template


class TestSuppressionListRemoval:
    def test_remove_from_suppression_list_success(self, client, notify_db, notify_db_session, sample_service):
        """Test successfully removing an email from suppression list"""
        # Create a template and notification to prove service has sent to this email
        template = create_template(sample_service, template_type="email")
        email_address = "test@example.com"
        create_notification(template=template, to_field=email_address, normalised_to=email_address.lower())
        with patch("app.service.rest.aws_ses_client") as mock_ses_client, patch("app.service.rest.Freshdesk") as mock_freshdesk:
            mock_ses_client.remove_email_from_suppression_list.return_value = True
            mock_freshdesk_instance = Mock()
            mock_freshdesk_instance.send_ticket.return_value = 201
            mock_freshdesk.return_value = mock_freshdesk_instance

            auth_header = create_authorization_header()
            response = client.post(
                f"/service/{sample_service.id}/remove-from-suppression-list",
                data=json.dumps({"email_address": email_address}),
                headers=[("Content-Type", "application/json"), auth_header],
            )

            assert response.status_code == 200
            json_resp = json.loads(response.get_data(as_text=True))
            assert "Successfully removed" in json_resp["message"]
            assert email_address in json_resp["message"]

            # Verify AWS SES client was called
            mock_ses_client.remove_email_from_suppression_list.assert_called_once_with(email_address)

            # Verify Freshdesk ticket was created
            mock_freshdesk.assert_called_once()
            mock_freshdesk_instance.send_ticket.assert_called_once()

    def test_remove_from_suppression_list_email_not_sent_by_service(self, client, notify_db, notify_db_session, sample_service):
        """Test that removal fails if service has never sent to this email"""
        email_address = "never-sent@example.com"

        auth_header = create_authorization_header()
        response = client.post(
            f"/service/{sample_service.id}/remove-from-suppression-list",
            data=json.dumps({"email_address": email_address}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404
        json_resp = json.loads(response.get_data(as_text=True))
        assert "has not sent any notifications" in json_resp["message"]

    def test_remove_from_suppression_list_invalid_email(self, client, notify_db, sample_service):
        """Test that invalid email address is rejected"""
        auth_header = create_authorization_header()
        response = client.post(
            f"/service/{sample_service.id}/remove-from-suppression-list",
            data=json.dumps({"email_address": "not-an-email"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        json_resp = json.loads(response.get_data(as_text=True))
        assert "email_address" in json_resp["message"]

    def test_remove_from_suppression_list_missing_email(self, client, notify_db, sample_service):
        """Test that missing email address is rejected"""
        auth_header = create_authorization_header()
        response = client.post(
            f"/service/{sample_service.id}/remove-from-suppression-list",
            data=json.dumps({}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        json_resp = json.loads(response.get_data(as_text=True))
        assert "email_address" in json_resp["message"]

    def test_remove_from_suppression_list_ses_client_error(self, client, notify_db, notify_db_session, sample_service):
        """Test that SES client errors are handled properly"""
        template = create_template(sample_service, template_type="email")
        email_address = "test@example.com"
        create_notification(template=template, to_field=email_address, normalised_to=email_address.lower())
        with patch("app.service.rest.aws_ses_client") as mock_ses_client:
            mock_ses_client.remove_email_from_suppression_list.side_effect = AwsSesClientException("SES error")

            auth_header = create_authorization_header()
            response = client.post(
                f"/service/{sample_service.id}/remove-from-suppression-list",
                data=json.dumps({"email_address": email_address}),
                headers=[("Content-Type", "application/json"), auth_header],
            )

            assert response.status_code == 500
            json_resp = json.loads(response.get_data(as_text=True))
            assert "Failed to remove email" in json_resp["message"]

    def test_remove_from_suppression_list_freshdesk_failure_does_not_fail_request(
        self, client, notify_db, notify_db_session, sample_service
    ):
        """Test that Freshdesk failures don't prevent successful removal"""
        template = create_template(sample_service, template_type="email")
        email_address = "test@example.com"
        create_notification(template=template, to_field=email_address, normalised_to=email_address.lower())

        with patch("app.service.rest.aws_ses_client") as mock_ses_client, patch("app.service.rest.Freshdesk") as mock_freshdesk:
            mock_ses_client.remove_email_from_suppression_list.return_value = True
            mock_freshdesk.side_effect = Exception("Freshdesk error")

            auth_header = create_authorization_header()
            response = client.post(
                f"/service/{sample_service.id}/remove-from-suppression-list",
                data=json.dumps({"email_address": email_address}),
                headers=[("Content-Type", "application/json"), auth_header],
            )

            # Should still succeed even if Freshdesk fails
            assert response.status_code == 200
            json_resp = json.loads(response.get_data(as_text=True))
            assert "Successfully removed" in json_resp["message"]

    def test_remove_from_suppression_list_service_not_found(self, client, notify_db):
        """Test that non-existent service returns 404"""
        import uuid

        fake_service_id = uuid.uuid4()

        auth_header = create_authorization_header()
        response = client.post(
            f"/service/{fake_service_id}/remove-from-suppression-list",
            data=json.dumps({"email_address": "test@example.com"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404

    def test_remove_from_suppression_list_case_insensitive_email_check(
        self, client, notify_db, notify_db_session, sample_service
    ):
        """Test that email address matching is case-insensitive"""
        template = create_template(sample_service, template_type="email")
        email_address = "Test@Example.COM"
        normalised_email = email_address.lower()
        create_notification(template=template, to_field=email_address, normalised_to=normalised_email)

        with patch("app.service.rest.aws_ses_client") as mock_ses_client, patch("app.service.rest.Freshdesk") as mock_freshdesk:
            mock_ses_client.remove_email_from_suppression_list.return_value = True
            mock_freshdesk_instance = Mock()
            mock_freshdesk_instance.send_ticket.return_value = 201
            mock_freshdesk.return_value = mock_freshdesk_instance

            auth_header = create_authorization_header()
            # Request with different case
            response = client.post(
                f"/service/{sample_service.id}/remove-from-suppression-list",
                data=json.dumps({"email_address": "test@example.com"}),
                headers=[("Content-Type", "application/json"), auth_header],
            )

            assert response.status_code == 200
