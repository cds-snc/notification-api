""" Test endpoints for the v3 notifications. """

import pytest
from app.authentication.auth import AuthError
from app.models import EMAIL_TYPE, KEY_TYPE_TEAM, SMS_TYPE
from app.service.service_data import ServiceData
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
    assert response_json['errors'][0]['error'] == 'BadRequest'
    assert 'message' in response_json['errors'][0]


@pytest.mark.parametrize(
    'request_data, expected_status_code',
    (
        (
            {
                'notification_type': SMS_TYPE,
                'phone_number': '+18006982411',
                'sms_sender_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            202,
        ),
        (
            {
                'notification_type': EMAIL_TYPE,
                'email_address': 'test@va.gov',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            202,
        ),
        (
            {
                'notification_type': SMS_TYPE,
                'recipient_identifier': {
                    'id_type': 'VAPROFILEID',
                    'id_value': 'some value',
                },
                'sms_sender_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            202,
        ),
        (
            {
                'notification_type': EMAIL_TYPE,
                'recipient_identifier': {
                    'id_type': 'EDIPI',
                    'id_value': 'some value',
                },
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            202,
        ),
        (
            {
                'notification_type': EMAIL_TYPE,
                'email_address': 'test@va.gov',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'something': 42,
            },
            400,
        ),
    ),
    ids=(
        'SMS with phone number',
        'e-mail with e-mail address',
        'SMS with recipient ID',
        'e-mail with recipient ID',
        'additional properties not allowed',
    ),
)
def test_post_v3_notifications(client, mocker, sample_api_key, sample_service, request_data, expected_status_code):
    """
    Test e-mail and SMS POST endpoints using "email_address", "phone_number", and "recipient_identifier".
    Also test POSTing with bad request data to verify a 400 response.  This test does not exhaustively test
    request data combinations because tests/app/v3/notifications/test_notification_schemas.py handles that.

    Also test the utility function, v3_send_notification, to send notifications directly (not via an API call).
    The route handlers call this function.

    Tests for authentication are in tests/app/test_route_authentication.py.
    """

    service = sample_service()
    api_key = sample_api_key(service=service, key_type=KEY_TYPE_TEAM)
    celery_mock = mocker.patch('app.v3.notifications.rest.v3_process_notification.delay')
    auth_header = create_authorization_header(api_key)

    response = client.post(
        path=url_for(f"v3.v3_notifications.v3_post_notification_{request_data['notification_type']}"),
        data=dumps(request_data),
        headers=(('Content-Type', 'application/json'), auth_header),
    )
    response_json = response.get_json()
    assert response.status_code == expected_status_code, response_json
    service_data = ServiceData(service)

    if expected_status_code == 202:
        assert isinstance(UUID(response_json['id']), UUID)
        request_data['id'] = response_json['id']
        celery_mock.assert_called_once_with(request_data, service.id, service.api_keys[0].id, KEY_TYPE_TEAM)

        # For the same request data, calling v3_send_notification directly, rather than through a route
        # handler, should also succeed.
        celery_mock.reset_mock()
        del request_data['id']
        request_data['id'] = v3_send_notification(request_data, service_data)
        assert isinstance(UUID(request_data['id']), UUID)
        celery_mock.assert_called_once_with(request_data, service.id, service.api_keys[0].id, KEY_TYPE_TEAM)
    elif expected_status_code == 400:
        assert response_json['errors'][0]['error'] == 'ValidationError'

        # For the same request data, calling v3_send_notification directly, rather than through a route
        # handler, should also raise ValidationError.
        with pytest.raises(ValidationError):
            v3_send_notification(request_data, service_data)

        celery_mock.assert_not_called()


def test_post_v3_notifications_email_denied(client, mocker, sample_api_key, sample_service):
    """
    Test trying to send e-mail with a service that does not have permission to send e-mail.
    The implementation should test permission before validating the request data.
    """

    service = sample_service(service_permissions=[SMS_TYPE])
    api_key = sample_api_key(service=service, key_type=KEY_TYPE_TEAM)
    assert not service.has_permissions(EMAIL_TYPE)

    celery_mock = mocker.patch('app.v3.notifications.rest.v3_process_notification.delay')
    auth_header = create_authorization_header(api_key)
    response = client.post(
        path=url_for('v3.v3_notifications.v3_post_notification_email'),
        data=dumps({}),
        headers=(('Content-Type', 'application/json'), auth_header),
    )
    assert response.status_code == 403
    response_json = response.get_json()
    assert response_json['errors'][0]['error'] == 'AuthError'
    assert (
        response_json['errors'][0]['message']
        == 'The service does not have permission to send this type of notification.'
    )
    celery_mock.assert_not_called()

    # For the same request data, calling v3_send_notification directly, rather than through a route
    # handler, should also raise AuthError.
    with pytest.raises(AuthError):
        v3_send_notification({'notification_type': EMAIL_TYPE}, ServiceData(service))
    celery_mock.assert_not_called()


def test_post_v3_notifications_sms_denied(client, mocker, sample_api_key, sample_service):
    """
    Test trying to send a SMS notification with a service that does not have permission to send SMS.
    The implementation should test permission before validating the request data.
    """

    service = sample_service(service_permissions=[EMAIL_TYPE])
    api_key = sample_api_key(service=service, key_type=KEY_TYPE_TEAM)
    assert not service.has_permissions(SMS_TYPE)

    celery_mock = mocker.patch('app.v3.notifications.rest.v3_process_notification.delay')
    auth_header = create_authorization_header(api_key)
    response = client.post(
        path=url_for('v3.v3_notifications.v3_post_notification_sms'),
        data=dumps({}),
        headers=(('Content-Type', 'application/json'), auth_header),
    )
    assert response.status_code == 403
    response_json = response.get_json()
    assert response_json['errors'][0]['error'] == 'AuthError'
    assert (
        response_json['errors'][0]['message']
        == 'The service does not have permission to send this type of notification.'
    )
    celery_mock.assert_not_called()

    # For the same request data, calling v3_send_notification directly, rather than through a route
    # handler, should also raise AuthError.
    with pytest.raises(AuthError):
        v3_send_notification({'notification_type': SMS_TYPE}, ServiceData(service))
    celery_mock.assert_not_called()


@pytest.mark.parametrize(
    'request_data',
    (
        {
            'notification_type': SMS_TYPE,
            'phone_number': 'This is not a phone number.',
            'sms_sender_id': '4f365dd4-332e-454d-94ff-e393463602db',
            'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
        },
        {
            'notification_type': SMS_TYPE,
            'phone_number': '+1270123456',
            'sms_sender_id': '4f365dd4-332e-454d-94ff-e393463602db',
            'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
        },
    ),
    ids=(
        'not a phone number',
        'not enough digits',
    ),
)
def test_post_v3_notifications_phone_number_not_possible(client, sample_api_key, request_data):
    """
    Test phone number strings that cannot be parsed.
    """
    api_key = sample_api_key(key_type=KEY_TYPE_TEAM)
    auth_header = create_authorization_header(api_key)
    response = client.post(
        path=url_for('v3.v3_notifications.v3_post_notification_sms'),
        data=dumps(request_data),
        headers=(('Content-Type', 'application/json'), auth_header),
    )
    bad_request_helper(response)


def test_post_v3_notifications_phone_number_not_valid(client, sample_api_key):
    """
    Test a possible phone number that is not valid (U.S. number for which area code doesn't exist).
    """

    request_data = {
        'notification_type': SMS_TYPE,
        'phone_number': '+1555123456',
        'sms_sender_id': '4f365dd4-332e-454d-94ff-e393463602db',
        'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
    }

    api_key = sample_api_key(key_type=KEY_TYPE_TEAM)
    auth_header = create_authorization_header(api_key)
    response = client.post(
        path=url_for('v3.v3_notifications.v3_post_notification_sms'),
        data=dumps(request_data),
        headers=(('Content-Type', 'application/json'), auth_header),
    )
    assert response.status_code == 400

    response_json = response.get_json()
    assert response_json['errors'][0]['error'] == 'BadRequest'
    assert response_json['errors'][0]['message'].endswith('is not a valid phone number.')


def test_post_v3_notifications_scheduled_for(client, mocker, sample_api_key):
    """
    The scheduled time must not be in the past or more than a calendar day in the future.
    """

    api_key = sample_api_key(key_type=KEY_TYPE_TEAM)
    celery_mock = mocker.patch('app.v3.notifications.rest.v3_process_notification.delay')
    auth_header = create_authorization_header(api_key)
    scheduled_for = datetime.now(timezone.utc) + timedelta(hours=2)
    email_request_data = {
        'notification_type': EMAIL_TYPE,
        'email_address': 'test@va.gov',
        'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
        'scheduled_for': scheduled_for.isoformat(),
    }
    sms_request_data = {
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
        'scheduled_for': scheduled_for.isoformat(),
    }

    #######################################################################
    # Test scheduled_for is acceptable.
    #######################################################################

    response = client.post(
        path=url_for('v3.v3_notifications.v3_post_notification_email'),
        data=dumps(email_request_data),
        headers=(('Content-Type', 'application/json'), auth_header),
    )
    response_json = response.get_json()

    # TODO 1602 - Delete when scheduled sending is implemented.
    assert response.status_code == 501, response_json
    assert response_json['errors'][0]['message'] == 'Scheduled sending is not implemented.'
    celery_mock.assert_not_called()

    # TODO 1602 - Uncomment when scheduled sending is implemented.
    # assert response.status_code == 202, response_json
    # email_request_data["id"] = response_json["id"]
    # celery_mock.assert_called_once_with(
    #     email_request_data, sample_service.id, sample_service.api_keys[0].id, KEY_TYPE_TEAM
    # )
    # celery_mock.reset_mock()
    # del email_request_data["id"]

    response = client.post(
        path=url_for('v3.v3_notifications.v3_post_notification_sms'),
        data=dumps(sms_request_data),
        headers=(('Content-Type', 'application/json'), auth_header),
    )
    response_json = response.get_json()

    # TODO 1602 - Delete when scheduled sending is implemented.
    assert response.status_code == 501, response_json
    assert response_json['errors'][0]['message'] == 'Scheduled sending is not implemented.'
    celery_mock.assert_not_called()

    # TODO 1602 - Uncomment when scheduled sending is implemented.
    # assert response.status_code == 202, response_json
    # sms_request_data["id"] = response_json["id"]
    # celery_mock.assert_called_once_with(
    #     sms_request_data, sample_service.id, sample_service.api_keys[0].id, KEY_TYPE_TEAM
    # )
    # celery_mock.reset_mock()
    # del sms_request_data["id"]

    #######################################################################
    # Test scheduled_for too far in the future and in the past.
    #######################################################################

    for bad_scheduled_for in (scheduled_for + timedelta(days=2), scheduled_for - timedelta(days=5)):
        email_request_data['scheduled_for'] = bad_scheduled_for.isoformat()
        response = client.post(
            path=url_for('v3.v3_notifications.v3_post_notification_email'),
            data=dumps(email_request_data),
            headers=(('Content-Type', 'application/json'), auth_header),
        )
        bad_request_helper(response)
        celery_mock.assert_not_called()

        sms_request_data['scheduled_for'] = bad_scheduled_for.isoformat()
        response = client.post(
            path=url_for('v3.v3_notifications.v3_post_notification_sms'),
            data=dumps(sms_request_data),
            headers=(('Content-Type', 'application/json'), auth_header),
        )
        bad_request_helper(response)
        celery_mock.assert_not_called()


@pytest.mark.parametrize(
    'notification_type, error_message',
    (
        (EMAIL_TYPE, 'You must provide an e-mail address or recipient identifier.'),
        (SMS_TYPE, 'You must provide a phone number or recipient identifier.'),
    ),
)
def test_post_v3_notifications_custom_validation_error_messages(
    client,
    sample_api_key,
    notification_type,
    error_message,
):
    """
    Send a request that has neither direct contact information nor a recipient identifier.  The response
    should have a custom validation error message because the default message is not helpful.
    """

    api_key = sample_api_key(key_type=KEY_TYPE_TEAM)
    auth_header = create_authorization_header(api_key)
    request_data = {
        'notification_type': notification_type,
        'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
    }

    response = client.post(
        path=url_for(f"v3.v3_notifications.v3_post_notification_{request_data['notification_type']}"),
        data=dumps(request_data),
        headers=(('Content-Type', 'application/json'), auth_header),
    )

    response_json = response.get_json()
    assert response.status_code == 400, response_json
    assert response_json['errors'][0]['message'] == error_message
