from flask import request, jsonify

from app import authenticated_service, vetext_client
from app.feature_flags import is_feature_enabled, FeatureFlag
from app.mobile_app import MobileAppRegistry, MobileAppType, DEAFULT_MOBILE_APP_TYPE

from app.models import (
    PUSH_TYPE
)
from app.notifications.validators import (
    check_service_has_permission
)
from app.schema_validation import validate
from app.v2.errors import BadRequestError
from app.v2.notifications import v2_notification_blueprint
from app.v2.notifications.notification_schemas import (
    push_notification_request
)
from app.va.vetext import (VETextRetryableException, VETextNonRetryableException, VETextBadRequestException)


@v2_notification_blueprint.route('/push', methods=['POST'])
def send_push_notification():
    if not is_feature_enabled(FeatureFlag.PUSH_NOTIFICATIONS_ENABLED):
        raise NotImplementedError()

    check_service_has_permission(PUSH_TYPE, authenticated_service.permissions)
    req_json = validate(request.get_json(), push_notification_request)
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
            req_json['recipient_identifier']['id_value'],
            req_json.get('personalisation')
        )
    except VETextBadRequestException as e:
        raise BadRequestError(message=e.message, status_code=400)
    except (VETextNonRetryableException, VETextRetryableException):
        return jsonify(result='error', message="Invalid response from downstream service"), 502
    else:
        return jsonify(result='success'), 201
