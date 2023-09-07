""" Test endpoints for the v3 notifications. """

import pytest
from app.models import EMAIL_TYPE, SMS_TYPE
from app.v3.notifications.rest import v3_send_notification
from datetime import datetime, timedelta, timezone
from flask import Response, url_for
from json import dumps
from jsonschema import ValidationError
from tests import create_authorization_header
from uuid import UUID


def bad_request_helper(response: Response):
    """
    Perform assertions for a BadRequest response for which the specific
    error message isn't important.
    """

    assert response.status_code == 400
    response_json = response.get_json()
    assert response_json["errors"][0]["error"] == "BadRequest"
    assert "message" in response_json["errors"][0]


@pytest.mark.parametrize(
    "request_data, expected_status_code",
    (
        (
            {
                "notification_type": SMS_TYPE,
                "phone_number": "+18006982411",
                "sms_sender_id": "4f365dd4-332e-454d-94ff-e393463602db",
                "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
            },
            202,
        ),
        (
            {
                "notification_type": EMAIL_TYPE,
                "email_address": "test@va.gov",
                "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
            },
            202,
        ),
        (
            {
                "notification_type": SMS_TYPE,
                "recipient_identifier": {
                    "id_type": "VAPROFILEID",
                    "id_value": "some value",
                },
                "sms_sender_id": "4f365dd4-332e-454d-94ff-e393463602db",
                "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
            },
            202,
        ),
        (
            {
                "notification_type": EMAIL_TYPE,
                "recipient_identifier": {
                    "id_type": "EDIPI",
                    "id_value": "some value",
                },
                "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
            },
            202,
        ),
        (
            {
                "notification_type": EMAIL_TYPE,
                "email_address": "test@va.gov",
                "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
                "something": 42,
            },
            400,
        ),
    ),
    ids=(
        "SMS with phone number",
        "e-mail with e-mail address",
        "SMS with recipient ID",
        "e-mail with recipient ID",
        "additional properties not allowed",
    )
)
def test_post_v3_notifications(notify_db_session, client, sample_service, request_data, expected_status_code):
    """
    Test e-mail and SMS POST endpoints using "email_address", "phone_number", and "recipient_identifier".
    Also test POSTing with bad request data to verify a 400 response.  This test does not exhaustively test
    request data combinations because tests/app/v3/notifications/test_notification_schemas.py handles that.

    Also test the utility function, v3_send_notification, to send notifications directly (not via an API call).
    The route handlers call this function.

    Tests for authentication are in tests/app/test_route_authentication.py.
    """

    # TODO 1361 - mock call to Celery apply_async

    auth_header = create_authorization_header(service_id=sample_service.id, key_type="team")
    response = client.post(
        path=url_for(f"v3.v3_notifications.v3_post_notification_{request_data['notification_type']}"),
        data=dumps(request_data),
        headers=(("Content-Type", "application/json"), auth_header)
    )
    assert response.status_code == expected_status_code, response.get_json()

    if expected_status_code == 202:
        assert isinstance(UUID(response.get_json().get("id")), UUID)
        assert isinstance(UUID(v3_send_notification(request_data)), UUID)
    elif expected_status_code == 400:
        assert response.get_json()["errors"][0]["error"] == "ValidationError"
        with pytest.raises(ValidationError):
            v3_send_notification(request_data)


@pytest.mark.parametrize(
    "request_data",
    (
        {
            "notification_type": SMS_TYPE,
            "phone_number": "This is not a phone number.",
            "sms_sender_id": "4f365dd4-332e-454d-94ff-e393463602db",
            "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
        },
        {
            "notification_type": SMS_TYPE,
            "phone_number": "+1270123456",
            "sms_sender_id": "4f365dd4-332e-454d-94ff-e393463602db",
            "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
        },
    ),
    ids=(
        "not a phone number",
        "not enough digits",
    )
)
def test_post_v3_notifications_phone_number_not_possible(notify_db_session, client, sample_service, request_data):
    """
    Test a phone number strings that cannot be parsed.
    """

    auth_header = create_authorization_header(service_id=sample_service.id, key_type="team")
    response = client.post(
        path=url_for("v3.v3_notifications.v3_post_notification_sms"),
        data=dumps(request_data),
        headers=(("Content-Type", "application/json"), auth_header)
    )
    bad_request_helper(response)


def test_post_v3_notifications_phone_number_not_valid(notify_db_session, client, sample_service):
    """
    Test a possible phone number that is not valid (U.S. number for which area code doesn't exist).
    """

    request_data = {
        "notification_type": SMS_TYPE,
        "phone_number": "+1555123456",
        "sms_sender_id": "4f365dd4-332e-454d-94ff-e393463602db",
        "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
    }

    auth_header = create_authorization_header(service_id=sample_service.id, key_type="team")
    response = client.post(
        path=url_for("v3.v3_notifications.v3_post_notification_sms"),
        data=dumps(request_data),
        headers=(("Content-Type", "application/json"), auth_header)
    )
    assert response.status_code == 400

    response_json = response.get_json()
    assert response_json["errors"][0]["error"] == "BadRequest"
    assert response_json["errors"][0]["message"].endswith("is not a valid phone number.")


def test_post_v3_notifications_scheduled_for(notify_db_session, client, sample_service):
    """
    The scheduled time must not be in the past or more than a calendar day in the future.
    """

    auth_header = create_authorization_header(service_id=sample_service.id, key_type="team")
    scheduled_for = datetime.now(timezone.utc) + timedelta(hours=2)
    email_request_data = {
        "notification_type": EMAIL_TYPE,
        "email_address": "test@va.gov",
        "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
        "scheduled_for": scheduled_for.isoformat(),
    }
    sms_request_data = {
        "notification_type": SMS_TYPE,
        "phone_number": "+18006982411",
        "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
        "scheduled_for": scheduled_for.isoformat(),
    }

    #######################################################################
    # Test scheduled_for is acceptable.
    #######################################################################

    response = client.post(
        path=url_for("v3.v3_notifications.v3_post_notification_email"),
        data=dumps(email_request_data),
        headers=(("Content-Type", "application/json"), auth_header)
    )
    assert response.status_code == 202, response.get_json()

    response = client.post(
        path=url_for("v3.v3_notifications.v3_post_notification_sms"),
        data=dumps(sms_request_data),
        headers=(("Content-Type", "application/json"), auth_header)
    )
    assert response.status_code == 202, response.get_json()

    #######################################################################
    # Test scheduled_for too far in the future and in the past.
    #######################################################################

    for bad_scheduled_for in (scheduled_for + timedelta(days=2), scheduled_for - timedelta(days=5)):
        email_request_data["scheduled_for"] = bad_scheduled_for.isoformat()
        response = client.post(
            path=url_for("v3.v3_notifications.v3_post_notification_email"),
            data=dumps(email_request_data),
            headers=(("Content-Type", "application/json"), auth_header)
        )
        bad_request_helper(response)

        sms_request_data["scheduled_for"] = bad_scheduled_for.isoformat()
        response = client.post(
            path=url_for("v3.v3_notifications.v3_post_notification_sms"),
            data=dumps(sms_request_data),
            headers=(("Content-Type", "application/json"), auth_header)
        )
        bad_request_helper(response)


@pytest.mark.parametrize(
    "notification_type, error_message",
    (
        (EMAIL_TYPE, "You must provide an e-mail address or recipient identifier."),
        (SMS_TYPE, "You must provide a phone number or recipient identifier."),
    )
)
def test_post_v3_notifications_custom_validation_error_messages(
    notify_db_session, client, sample_service, notification_type, error_message
):
    """
    Send a request that has neither direct contact information nor a recipient identifier.  The response
    should have a custom validation error message because the default message is not helpful.
    """

    auth_header = create_authorization_header(service_id=sample_service.id, key_type="team")
    request_data = {
        "notification_type": notification_type,
        "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
    }

    response = client.post(
        path=url_for(f"v3.v3_notifications.v3_post_notification_{request_data['notification_type']}"),
        data=dumps(request_data),
        headers=(("Content-Type", "application/json"), auth_header)
    )

    response_json = response.get_json()
    assert response.status_code == 400, response_json
    assert response_json["errors"][0]["message"] == error_message
