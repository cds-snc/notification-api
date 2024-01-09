""" Implement v3 endpoints for the Notification model. """

import phonenumbers
from app import authenticated_service
from app.authentication.auth import AuthError
from app.celery.v3.notification_tasks import v3_process_notification
from app.models import EMAIL_TYPE, KEY_TYPE_NORMAL, SMS_TYPE
from app.service.service_data import ServiceData
from app.v3.notifications.notification_schemas import (
    notification_v3_post_email_request_schema,
    notification_v3_post_sms_request_schema,
)
from datetime import datetime, timezone
from flask import Blueprint, request
from jsonschema import FormatChecker
from jsonschema.validators import Draft202012Validator
from uuid import uuid4
from werkzeug.exceptions import BadRequest

v3_notifications_blueprint = Blueprint('v3_notifications', __name__, url_prefix='/notifications')

#########################################################################
# Create instances of Draft202012Validator to validate post request data.
#########################################################################

v3_notifications_post_email_request_validator = Draft202012Validator(
    notification_v3_post_email_request_schema, format_checker=FormatChecker(['date-time', 'email', 'uuid'])
)

v3_notifications_post_sms_request_validator = Draft202012Validator(
    notification_v3_post_sms_request_schema, format_checker=FormatChecker(['date-time', 'uuid'])
)

#########################################################################


@v3_notifications_blueprint.route('/email', methods=['POST'])
def v3_post_notification_email():
    request_data = request.get_json()
    request_data['notification_type'] = EMAIL_TYPE

    try:
        # This might trigger various exceptions with associated error handlers.
        return {'id': v3_send_notification(request_data, authenticated_service)}, 202
    except ValueError as e:
        # This should trigger an error handler for BadRequest that returns a 400 response.
        raise BadRequest from e


@v3_notifications_blueprint.route('/sms', methods=['POST'])
def v3_post_notification_sms():
    request_data = request.get_json()
    request_data['notification_type'] = SMS_TYPE

    try:
        # This might trigger various exceptions with associated error handlers.
        return {'id': v3_send_notification(request_data, authenticated_service)}, 202
    except (phonenumbers.phonenumberutil.NumberParseException, ValueError) as e:
        # This should trigger an error handler for BadRequest that returns a 400 response.
        raise BadRequest from e


def v3_send_notification(
    request_data: dict,
    service_data: ServiceData,
) -> str:
    """
    This function can be called directly to send notifications without having to make API requests.
    In that use case, the upstream code is responsbile for populating notification_type and for
    catching exceptions.
    """

    # Ensure the service has permission to send a notification of the given type.
    if (
        (request_data['notification_type'] == EMAIL_TYPE and not service_data.has_permissions(EMAIL_TYPE))
        or (request_data['notification_type'] == SMS_TYPE and not service_data.has_permissions(SMS_TYPE))
        # TODO - test for international phone numbers (needs a unit test too)
    ):
        # TODO - more specific for phone numbers (i.e. service can't send international)
        raise AuthError('The service does not have permission to send this type of notification.', 403)

    # This might raise jsonschema.ValidationError.
    if request_data['notification_type'] == EMAIL_TYPE:
        v3_notifications_post_email_request_validator.validate(request_data)
    elif request_data['notification_type'] == SMS_TYPE:
        v3_notifications_post_sms_request_validator.validate(request_data)
    else:
        raise RuntimeError('Unrecognized notification type.  This is a programming error.')

    if 'scheduled_for' in request_data:
        # The scheduled time must not be in the past or more than a calendar day in the future.
        # The time should be in ISO 8601 format with timezone data, as required by the validator.
        scheduled_for = datetime.fromisoformat(request_data['scheduled_for'])

        right_now = datetime.now(timezone.utc)
        if scheduled_for < right_now:
            raise ValueError('The scheduled time cannot be in the past.')

        if (scheduled_for - right_now).days > 1:
            raise ValueError('The scheduled time cannot be more than one calendar day in the future.')

        raise NotImplementedError('Scheduled sending is not implemented.')

    if 'phone_number' in request_data:
        # This might raise phonenumbers.phonenumberutil.NumberParseException.
        phone_number = phonenumbers.parse(request_data['phone_number'])

        # This is a possible phone number, but is it in an assigned exchange (valid area code, etc.)?
        if not phonenumbers.is_valid_number(phone_number):
            raise ValueError(f"{request_data['phone_number']} is not a valid phone number.")

    # This has the side effect of modifying the input in the upstream code.
    request_data['id'] = str(uuid4())

    # Initiate a Celery task to process the validated request data.  This does not block.
    # TODO - v2 uses the imported value "api_user" for the api_key.
    # Does the list service_data.api_keys ever have more than one element?
    v3_process_notification.delay(
        request_data,
        service_data.id,
        service_data.api_keys[0].id if service_data.api_keys else None,
        service_data.api_keys[0].key_type if service_data.api_keys else KEY_TYPE_NORMAL,
    )
    return request_data['id']
