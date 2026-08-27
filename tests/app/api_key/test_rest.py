import pytest
from flask import url_for

from app.dao.api_key_dao import get_api_key_by_secret, get_unsigned_secret
from app.models import KEY_TYPE_NORMAL
from tests import create_sre_authorization_header
from tests.app.db import (
    create_api_key,
    create_notification,
    create_service,
    create_template,
    save_notification,
)


def test_get_api_key_stats_with_sends(admin_request, notify_db, notify_db_session):
    service = create_service(service_name="Service 1")
    api_key = create_api_key(service)
    template = create_template(service=service, template_type="email")
    total_sends = 10

    for x in range(total_sends):
        notification = create_notification(template=template, api_key=api_key)
        save_notification(notification)

    api_key_stats = admin_request.get("api_key.get_api_key_stats", api_key_id=api_key.id)["data"]

    assert api_key_stats["api_key_id"] == str(api_key.id)
    assert api_key_stats["email_sends"] == total_sends
    assert api_key_stats["sms_sends"] == 0
    assert api_key_stats["total_sends"] == total_sends


def test_get_api_key_stats_no_sends(admin_request, notify_db, notify_db_session):
    service = create_service(service_name="Service 2")
    api_key = create_api_key(service)

    api_key_stats = admin_request.get("api_key.get_api_key_stats", api_key_id=api_key.id)["data"]

    assert api_key_stats["api_key_id"] == str(api_key.id)
    assert api_key_stats["email_sends"] == 0
    assert api_key_stats["sms_sends"] == 0
    assert api_key_stats["total_sends"] == 0
    assert api_key_stats["last_send"] is None


def test_get_api_keys_ranked(admin_request, notify_db, notify_db_session):
    service = create_service(service_name="Service 1")
    api_key_1 = create_api_key(service, key_type=KEY_TYPE_NORMAL, key_name="Key 1")
    api_key_2 = create_api_key(service, key_type=KEY_TYPE_NORMAL, key_name="Key 2")
    template_email = create_template(service=service, template_type="email")
    total_sends = 10

    save_notification(create_notification(template=template_email, api_key=api_key_1))
    for x in range(total_sends):
        save_notification(create_notification(template=template_email, api_key=api_key_1))
        save_notification(create_notification(template=template_email, api_key=api_key_2))

    api_keys_ranked = admin_request.get("api_key.get_api_keys_ranked", n_days_back=2)["data"]

    assert api_keys_ranked[0]["api_key_name"] == api_key_1.name
    assert api_keys_ranked[0]["service_name"] == service.name
    assert api_keys_ranked[0]["sms_notifications"] == 0
    assert api_keys_ranked[0]["email_notifications"] == total_sends + 1
    assert api_keys_ranked[0]["total_notifications"] == total_sends + 1
    assert "last_notification_created" in api_keys_ranked[0]

    assert api_keys_ranked[1]["api_key_name"] == api_key_2.name
    assert api_keys_ranked[1]["service_name"] == service.name
    assert api_keys_ranked[1]["sms_notifications"] == 0
    assert api_keys_ranked[1]["email_notifications"] == total_sends
    assert api_keys_ranked[1]["total_notifications"] == total_sends
    assert "last_notification_created" in api_keys_ranked[0]


class TestApiKeyRevocation:
    def test_revoke_api_keys_with_valid_auth_revokes_and_notifies_user(self, client, notify_db, notify_db_session, mocker):
        notify_users = mocker.patch("app.api_key.rest.send_api_key_revocation_email")

        service = create_service(service_name="Service 1")
        api_key_1 = create_api_key(service, key_type=KEY_TYPE_NORMAL, key_name="Key 1")
        unsigned_secret = get_unsigned_secret(api_key_1.id)

        # Create token expected from the frontend
        unsigned_secret = f"gcntfy-keyname-{service.id}-{unsigned_secret}"

        sre_auth_header = create_sre_authorization_header()
        response = client.post(
            url_for("sre_tools.revoke_api_keys"),
            headers=[sre_auth_header],
            json={"token": unsigned_secret, "type": "cds-tester", "url": "https://example.com", "source": "cds-tester"},
        )

        # Get api key from DB
        api_key_1 = get_api_key_by_secret(unsigned_secret)
        assert response.status_code == 201
        assert api_key_1.expiry_date is not None
        assert api_key_1.compromised_key_info["type"] == "cds-tester"
        assert api_key_1.compromised_key_info["url"] == "https://example.com"
        assert api_key_1.compromised_key_info["source"] == "cds-tester"
        assert api_key_1.compromised_key_info["time_of_revocation"]

        notify_users.assert_called_once()

    def test_revoke_api_keys_fails_with_no_auth(self, client, notify_db, notify_db_session, mocker):
        service = create_service(service_name="Service 1")
        api_key_1 = create_api_key(service, key_type=KEY_TYPE_NORMAL, key_name="Key 1")
        unsigned_secret = get_unsigned_secret(api_key_1.id)

        response = client.post(
            url_for("sre_tools.revoke_api_keys"),
            headers=[],
            json={"token": unsigned_secret, "type": "cds-tester", "url": "https://example.com", "source": "cds-tester"},
        )

        assert response.status_code == 401

    @pytest.mark.parametrize(
        "payload,expected_response",  # Added comma here
        (
            (
                {
                    # no token
                    "type": "cds-tester",
                    "url": "https://example.com",
                    "source": "cds-tester",
                },
                400,
            ),
            (
                {
                    "token": "token",
                    # no type
                    "url": "https://example.com",
                    "source": "cds-tester",
                },
                400,
            ),
            (
                {
                    "token": "token",
                    "type": "cds-tester",
                    # no url
                    "source": "cds-tester",
                },
                400,
            ),
            (
                {
                    "token": "token",
                    "type": "cds-tester",
                    "url": "https://example.com",
                    # no source
                },
                400,
            ),
            (
                {
                    # no anything
                },
                400,
            ),
            (
                {"token": "token", "type": "cds-tester", "url": "https://example.com", "source": "cds-tester"},
                200,
            ),  # invalid token
        ),
    )
    def test_revoke_api_keys_fails_for_missing_params_or_invalid_payload(
        self, client, notify_db, notify_db_session, mocker, payload, expected_response
    ):
        sre_auth_header = create_sre_authorization_header()
        response = client.post(
            url_for("sre_tools.revoke_api_keys"),
            headers=[sre_auth_header],
            json=payload,
        )

        assert response.status_code == expected_response
