import json

from celery.exceptions import CeleryError
from jsonschema import ValidationError
from kombu.exceptions import OperationalError
from flask import current_app, jsonify, request

from app import authenticated_service, mobile_app_registry, vetext_client
from app.celery.provider_tasks import deliver_push
from app.config import QueueNames
from app.constants import PUSH_TYPE
from app.mobile_app import DEFAULT_MOBILE_APP_TYPE, MobileAppType
from app.schema_validation import validate
from app.utils import get_public_notify_type_text
from app.v2.errors import BadRequestError
from app.v2.notifications import v2_notification_blueprint
from app.v2.dataclasses import V2PushPayload
from app.v2.notifications.notification_schemas import push_notification_broadcast_request, push_notification_request


@v2_notification_blueprint.route('/push', methods=['POST'])
def send_push_notification():
    return push_notification_helper(push_notification_request)


@v2_notification_blueprint.route('/push/broadcast', methods=['POST'])
def send_push_broadcast_notification():
    return push_notification_helper(push_notification_broadcast_request)


def push_notification_helper(schema: dict):
    """
    Note that this helper cannot be called other than as part of a request because it accesses
    the Flask "request" instance.
    """
    if not authenticated_service.has_permissions(PUSH_TYPE):
        public_notify_type = get_public_notify_type_text(PUSH_TYPE, plural=True)

        raise BadRequestError(
            message=f'Service is not allowed to send {public_notify_type}',
            status_code=403,
        )

    validated_payload = validate_push_payload(schema)

    vetext_formatted_payload = vetext_client.format_for_vetext(validated_payload)

    current_app.logger.debug(
        'Attempting to call deliver_push celery task with validated payload: %s',
        vetext_formatted_payload,
    )

    try:
        # Choosing to use the email queue for push to limit the number of empty queues
        deliver_push.apply_async(
            args=(vetext_formatted_payload,),
            queue=QueueNames.SEND_EMAIL,
        )
    except (CeleryError, OperationalError):
        current_app.logger.exception('Failed to enqueue deliver_push request')
        response = jsonify(result='error', message='VA Notify service impaired, please try again'), 503
    else:
        response = jsonify(result='success'), 201
    # Flask turns the tuple into a json and status_code
    return response


def validate_push_payload(schema: dict[str, str]) -> V2PushPayload:
    """Validate an incoming push request.

    Args:
        schema (dict[str, str]): The incoming request

    Raises:
        BadRequestError: Failed validation

    Returns:
        dict[str, str]: Validated request dictionary
    """
    try:
        req_json: dict[str, str] = validate(request.get_json(), schema)

        # Validate the application they sent us is valid or use the default
        # We currenlty only support VA Flagship App, but this is a placeholder for future apps
        if 'mobile_app' in req_json:
            app_sid = mobile_app_registry.get_app(MobileAppType[req_json['mobile_app']]).sid
        else:
            app_sid = mobile_app_registry.get_app(DEFAULT_MOBILE_APP_TYPE).sid
    except (KeyError, TypeError) as e:
        current_app.logger.warning('Push request failed validation due to mobile app setup: %s', e)
        raise BadRequestError(message=str(e), status_code=400)
    except ValidationError as e:
        current_app.logger.warning('Push request failed validation: %s', e)
        error_data = json.loads(e.message)
        error_data['errors'] = error_data['errors'][0]
        raise e

    current_app.logger.info(
        'Push request validated successfully for %s with SID %s',
        req_json.get('mobile_app', DEFAULT_MOBILE_APP_TYPE),
        app_sid,
    )

    # Use get() on optionals - schema validated it is correct
    payload = V2PushPayload(
        app_sid,
        req_json['template_id'],
        req_json.get('recipient_identifier', {}).get('id_value'),  # ICN
        req_json.get('topic_sid'),
        req_json.get('personalisation'),
    )
    current_app.logger.debug('V2PushPayload is: %s', payload)
    return payload
