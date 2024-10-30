from app import authenticated_service, vetext_client
from app.constants import PUSH_TYPE
from app.feature_flags import is_feature_enabled, FeatureFlag
from app.mobile_app import MobileAppRegistry, MobileAppType, DEAFULT_MOBILE_APP_TYPE
from app.schema_validation import validate
from app.utils import get_public_notify_type_text
from app.v2.errors import BadRequestError
from app.v2.notifications import v2_notification_blueprint
from app.v2.notifications.notification_schemas import push_notification_request, push_notification_broadcast_request
from app.va.vetext import VETextRetryableException, VETextNonRetryableException, VETextBadRequestException
from flask import request, jsonify


@v2_notification_blueprint.route('/push', methods=['POST'])
def send_push_notification():
    return push_notification_helper(push_notification_request, False)


@v2_notification_blueprint.route('/push/broadcast', methods=['POST'])
def send_push_broadcast_notification():
    return push_notification_helper(push_notification_broadcast_request, True)


def push_notification_helper(schema: dict, is_broadcast: bool):
    """
    Note that this helper cannot be called other than as part of a request because it accesses
    the Flask "request" instance.
    """

    if not is_feature_enabled(FeatureFlag.PUSH_NOTIFICATIONS_ENABLED):
        raise NotImplementedError()

    if not authenticated_service.has_permissions(PUSH_TYPE):
        raise BadRequestError(
            message='Service is not allowed to send {}'.format(get_public_notify_type_text(PUSH_TYPE, plural=True))
        )

    req_json = validate(request.get_json(), schema)
    registry = MobileAppRegistry()

    if req_json.get('mobile_app'):
        app_instance = registry.get_app(MobileAppType[req_json['mobile_app']])
    else:
        app_instance = registry.get_app(DEAFULT_MOBILE_APP_TYPE)

    if not app_instance:
        return jsonify(result='error', message='Mobile app is not initialized'), 503
    try:
        vetext_client.send_push_notification(
            app_instance.sid,
            req_json['template_id'],
            req_json['topic_sid'] if is_broadcast else req_json['recipient_identifier']['id_value'],
            is_broadcast,
            req_json.get('personalisation'),
        )
    except VETextBadRequestException as e:
        raise BadRequestError(message=e.message, status_code=400)
    except (VETextNonRetryableException, VETextRetryableException):
        return jsonify(result='error', message='Invalid response from downstream service'), 502
    else:
        return jsonify(result='success'), 201
