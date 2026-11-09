import pytest
from flask import current_app, json
from notifications_python_client.authentication import create_jwt_token

from app.authentication.auth import AUTH_TYPES
from app.models import EMAIL_TYPE
from tests import create_authorization_header
from tests.app.db import create_template

SIMULATED_EMAIL = "simulate-delivered@notification.canada.ca"
STATIC_LIMIT = 50_000
PERSONALISATION_LIMIT = 50_000


class TestEmailSizeLimits:
    """Email size limits for template creation, template update, and v2 send.

    Limits under test:
    - Static template content: EMAIL_CHAR_COUNT_LIMIT (50,000 characters).
    - Personalisation values combined: PERSONALISATION_SIZE_LIMIT (50,000).
    - Rendered email body (template + variables): EMAIL_CHAR_COUNT_LIMIT (50,000).
    """

    @pytest.fixture
    def mock_send_limits(self, mocker):
        annual = {
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
            "total_sms_billable_units_fiscal_year_to_yesterday": 0,
        }
        mocker.patch("app.v2.notifications.post_notifications.get_annual_limit_notifications_v2", return_value=annual)
        mocker.patch("app.notifications.validators.get_annual_limit_notifications_v2", return_value=annual)
        return mocker.patch("app.email_normal_publish.publish")

    @staticmethod
    def _post_template(client, api_key, name, content, category):
        return client.post(
            "/v2/manage-template",
            data=json.dumps(
                {
                    "name": name,
                    "template_type": EMAIL_TYPE,
                    "subject": "Subject",
                    "content": content,
                    "template_category_id": str(category.id),
                }
            ),
            headers=[("Content-Type", "application/json"), create_authorization_header(api_key=api_key)],
        )

    @staticmethod
    def _send(client, service, template_id, personalisation, email_address=None):
        return client.post(
            path="v2/notifications/email",
            data=json.dumps(
                {
                    "email_address": email_address or service.users[0].email_address,
                    "template_id": str(template_id),
                    "personalisation": personalisation,
                }
            ),
            headers=[
                ("Content-Type", "application/json"),
                create_authorization_header(service_id=service.id),
            ],
        )

    # Template creation and update (static size)

    def test_create_template_over_50k_chars_returns_400(
        self, client, sample_template_category, create_api_key_with_manage_api_perm
    ):
        response = self._post_template(
            client,
            create_api_key_with_manage_api_perm,
            "Too big",
            "A" * (STATIC_LIMIT + 1),
            sample_template_category,
        )

        assert response.status_code == 400
        assert "greater than the limit" in response.get_data(as_text=True)

    def test_create_template_at_50k_chars_returns_201(
        self, client, sample_template_category, create_api_key_with_manage_api_perm
    ):
        response = self._post_template(
            client,
            create_api_key_with_manage_api_perm,
            "Exactly at limit",
            "A" * STATIC_LIMIT,
            sample_template_category,
        )

        assert response.status_code == 201

    def test_patch_template_over_50k_chars_returns_400(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="Short body")

        response = client.patch(
            f"/v2/manage-template/{template.id}",
            data=json.dumps({"content": "A" * (STATIC_LIMIT + 1)}),
            headers=[
                ("Content-Type", "application/json"),
                create_authorization_header(api_key=create_api_key_with_manage_api_perm),
            ],
        )

        assert response.status_code == 400

    # Send: personalisation (variable) size

    def test_send_personalisation_combined_over_50000_returns_400(self, client, sample_service, mock_send_limits):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((a))((b))")
        personalisation = {"a": "A" * 25_000, "b": "B" * 25_001}

        response = self._send(client, sample_service, template.id, personalisation)

        assert response.status_code == 400
        assert not mock_send_limits.called

    def test_send_personalisation_at_50000_returns_201(self, client, sample_service, mock_send_limits):
        # The value is unused by the template, so the rendered body stays small.
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="Hello")

        response = self._send(client, sample_service, template.id, {"payload": "A" * PERSONALISATION_LIMIT})

        assert response.status_code == 201
        assert mock_send_limits.called

    # Send: rendered body size (static + variables)

    def test_send_rendered_body_at_50000_chars_returns_201(self, client, sample_service, mock_send_limits):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))")

        response = self._send(client, sample_service, template.id, {"payload": "A" * STATIC_LIMIT})

        assert response.status_code == 201
        assert mock_send_limits.called

    def test_send_single_variable_rendered_over_50000_chars_returns_400(self, client, sample_service, mock_send_limits):
        # Value (50,001) is under the 51,200 personalisation limit, but the rendered body exceeds 50,000.
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))")

        response = self._send(client, sample_service, template.id, {"payload": "A" * (STATIC_LIMIT + 1)})

        assert response.status_code == 400
        assert not mock_send_limits.called

    def test_send_template_plus_personalisation_at_50000_returns_201(self, client, sample_service, mock_send_limits):
        # Static text (25,000) and personalisation (25,000) combine to exactly 50,000 rendered characters.
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="S" * 25_000 + "((payload))")

        response = self._send(client, sample_service, template.id, {"payload": "A" * 25_000})

        assert response.status_code == 201
        assert mock_send_limits.called

    def test_send_template_plus_personalisation_over_50000_returns_400(self, client, sample_service, mock_send_limits):
        # Static text (26,000) and personalisation (26,000) are each under their limits.
        # Combined rendered size is 52,000, which is over 50,000.
        template = create_template(
            sample_service,
            template_type=EMAIL_TYPE,
            content="S" * 26_000 + "((payload))",
        )

        response = self._send(client, sample_service, template.id, {"payload": "A" * 26_000})

        assert response.status_code == 400
        assert not mock_send_limits.called

    def test_send_repeated_variable_rendered_over_50000_returns_400(self, client, sample_service, mock_send_limits):
        # One 26,000-char value is used twice. Personalisation counts it once (26,000),
        # but the rendered body is about 52,000 characters.
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))\nX\n((payload))")

        response = self._send(client, sample_service, template.id, {"payload": "A" * 26_000})

        assert response.status_code == 400
        assert not mock_send_limits.called

    def test_send_simulated_recipient_oversized_rendered_body_returns_400(self, client, sample_service, mock_send_limits):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))\nX\n((payload))")

        response = self._send(client, sample_service, template.id, {"payload": "A" * 26_000}, email_address=SIMULATED_EMAIL)

        assert response.status_code == 400

    # Admin send path (service/<id>/send-notification) also calls validate_template

    @pytest.fixture
    def mock_admin_send(self, mocker):
        return mocker.patch("app.service.send_notification.send_notification_to_queue")

    @staticmethod
    def _admin_send(client, service, template_id, personalisation):
        token = create_jwt_token(
            current_app.config["ADMIN_CLIENT_SECRET"], client_id=current_app.config["ADMIN_CLIENT_USER_NAME"]
        )
        return client.post(
            f"/service/{service.id}/send-notification",
            json={
                "to": service.users[0].email_address,
                "template_id": str(template_id),
                "created_by": str(service.users[0].id),
                "personalisation": personalisation,
            },
            headers=[("Content-Type", "application/json"), ("Authorization", f"{AUTH_TYPES[0][0]} {token}")],
        )

    def test_admin_send_rendered_body_over_50000_returns_400(self, client, sample_service, mock_admin_send):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))\nX\n((payload))")

        response = self._admin_send(client, sample_service, template.id, {"payload": "A" * 26_000})

        assert response.status_code == 400
        assert "greater than the limit" in response.get_data(as_text=True)
        assert not mock_admin_send.called

    def test_admin_send_rendered_body_at_50000_returns_201(self, client, sample_service, mock_admin_send):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))")

        response = self._admin_send(client, sample_service, template.id, {"payload": "A" * STATIC_LIMIT})

        assert response.status_code == 201
        assert mock_admin_send.called
