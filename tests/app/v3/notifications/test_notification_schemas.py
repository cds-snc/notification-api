"""Test the schemas for /v3/notifications."""

import pytest
from app.models import EMAIL_TYPE, SMS_TYPE
from app.v3.notifications.notification_schemas import (
    notification_v3_post_email_request_schema,
    notification_v3_post_sms_request_schema,
)
from app.v3.notifications.rest import (
    v3_notifications_post_email_request_validator,
    v3_notifications_post_sms_request_validator,
)
from jsonschema import ValidationError


def test_notification_v3_post_request_schemas():
    """
    Test that the schemas declared in app/v3/notifications/notification_schemas.py are valid
    with the validators declared in app/v3/notifications/rest.py.
    """

    # These checks should not raise SchemaError.
    v3_notifications_post_email_request_validator.check_schema(notification_v3_post_email_request_schema)
    v3_notifications_post_sms_request_validator.check_schema(notification_v3_post_sms_request_schema)


def test_v3_notifications_post_email_request_validator_requires_notification_type():
    post_data = {
        'notification_type': EMAIL_TYPE,
        'email_address': 'test@va.gov',
        'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
    }

    # This should not raise ValidationError.
    v3_notifications_post_email_request_validator.validate(post_data)

    del post_data['notification_type']
    with pytest.raises(ValidationError):
        v3_notifications_post_email_request_validator.validate(post_data)


def test_v3_notifications_post_sms_request_validator_requires_notification_type():
    post_data = {
        'notification_type': SMS_TYPE,
        'phone_number': '+12701234567',
        'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
    }

    # This should not raise ValidationError.
    v3_notifications_post_sms_request_validator.validate(post_data)

    del post_data['notification_type']
    with pytest.raises(ValidationError):
        v3_notifications_post_sms_request_validator.validate(post_data)


@pytest.mark.parametrize(
    'post_data, should_validate',
    (
        (
            {
                'email_address': 'test@va.gov',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            True,
        ),
        (
            {
                'email_address': 'not an e-mail address',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            False,
        ),
        (
            {
                'email_address': 'test@va.gov',
            },
            False,
        ),
        (
            {
                'email_address': 'test@va.gov',
                'template_id': 'not a UUID4',
            },
            False,
        ),
        (
            {
                'recipient_identifier': {
                    'id_type': 'EDIPI',
                    'id_value': 'some value',
                },
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            True,
        ),
        (
            {
                'email_address': 'test@va.gov',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'something': 42,
            },
            False,
        ),
        (
            {
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            False,
        ),
        (
            {
                'email_address': 'test@va.gov',
                'recipient_identifier': {
                    'id_type': 'EDIPI',
                    'id_value': 'some value',
                },
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            True,
        ),
        (
            {
                'email_address': 'test@va.gov',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'billing_code': 'billing code',
                'client_reference': 'client reference',
                'email_reply_to_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'personalisation': {
                    'test_file': {
                        'file': 'string',
                        'filename': 'file name',
                        'sending_method': 'link',
                    },
                },
                'reference': 'reference',
                'scheduled_for': '2023-09-06T19:55:23.592973+00:00',
            },
            True,
        ),
        (
            {
                'email_address': 'test@va.gov',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'personalisation': {
                    'test1': 'This is not a file.',
                    'test2': 'ditto',
                },
            },
            True,
        ),
        (
            {
                'email_address': 'test@va.gov',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'personalisation': {
                    'test1': 'This is not a file.',
                    'test2': 'ditto',
                    'test_file': {
                        'file': 'string',
                        'filename': 'file name',
                        'sending_method': 'link',
                    },
                },
            },
            True,
        ),
        (
            {
                'email_address': 'test@va.gov',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'scheduled_for': 'not a date-time',
            },
            False,
        ),
    ),
    ids=(
        'send with e-mail address',
        'bad e-mail address',
        'no template_id',
        'template_id is not a valid uuid',
        'send with recipient ID',
        'additional properties not allowed',
        'neither "email_address" nor recipient ID',
        'send with "email_address" and recipient ID',
        'all optional fields including file personalisation',
        'non-file personalisation',
        'file and non-file personalisation',
        'scheduled_for not a date-time',
    ),
)
def test_v3_notifications_post_email_request_validator(post_data: dict, should_validate: bool):
    """
    Test schema validation using the validator declared in app/v3/notifications/rest.py.
    """

    post_data['notification_type'] = EMAIL_TYPE

    if should_validate:
        v3_notifications_post_email_request_validator.validate(post_data)
    else:
        with pytest.raises(ValidationError):
            v3_notifications_post_email_request_validator.validate(post_data)


@pytest.mark.parametrize(
    'post_data, should_validate',
    (
        (
            {
                'phone_number': '+12701234567',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            True,
        ),
        (
            {
                'phone_number': 42,
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            False,
        ),
        (
            {
                'phone_number': '+12701234567',
            },
            False,
        ),
        (
            {
                'phone_number': '+12701234567',
                'template_id': 'not a UUID4',
            },
            False,
        ),
        (
            {
                'recipient_identifier': {
                    'id_type': 'EDIPI',
                    'id_value': 'some value',
                },
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            True,
        ),
        (
            {
                'phone_number': '+12701234567',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'something': 42,
            },
            False,
        ),
        (
            {
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            False,
        ),
        (
            {
                'phone_number': '+12701234567',
                'recipient_identifier': {
                    'id_type': 'EDIPI',
                    'id_value': 'some value',
                },
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
            },
            True,
        ),
        (
            {
                'phone_number': '+12701234567',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'billing_code': 'billing code',
                'client_reference': 'client reference',
                'sms_sender_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'personalisation': {
                    'test_file': {
                        'file': 'string',
                        'filename': 'file name',
                        'sending_method': 'link',
                    },
                },
                'reference': 'reference',
                'scheduled_for': '2023-09-06T19:55:23.592973+00:00',
            },
            True,
        ),
        (
            {
                'phone_number': '+12701234567',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'personalisation': {
                    'test1': 'This is not a file.',
                    'test2': 'ditto',
                },
            },
            True,
        ),
        (
            {
                'phone_number': '+12701234567',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'personalisation': {
                    'test1': 'This is not a file.',
                    'test2': 'ditto',
                    'test_file': {
                        'file': 'string',
                        'filename': 'file name',
                        'sending_method': 'link',
                    },
                },
            },
            True,
        ),
        (
            {
                'phone_number': '+12701234567',
                'template_id': '4f365dd4-332e-454d-94ff-e393463602db',
                'scheduled_for': 'not a date-time',
            },
            False,
        ),
    ),
    ids=(
        'send with phone number',
        "phone number isn't a string",
        'no template_id',
        'template_id is not a valid uuid',
        'send with recipient ID',
        'additional properties not allowed',
        'neither "phone_number" nor recipient ID',
        '"phone_number" and recipient ID',
        'all optional fields including file personalisation',
        'non-file personalisation',
        'file and non-file personalisation',
        'scheduled_for not a date-time',
    ),
)
def test_v3_notifications_post_sms_request_validator(post_data: dict, should_validate: bool):
    """
    Test schema validation using the validator declared in app/v3/notifications/rest.py.
    Note that JSON schema only validates that phone numbers are strings.
    """

    post_data['notification_type'] = SMS_TYPE

    if should_validate:
        v3_notifications_post_sms_request_validator.validate(post_data)
    else:
        with pytest.raises(ValidationError):
            v3_notifications_post_sms_request_validator.validate(post_data)
