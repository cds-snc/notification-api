from datetime import datetime
from flask import Blueprint, current_app, jsonify, request
from jsonschema.exceptions import ValidationError
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound

from app import statsd_client
from app.clients.email.govdelivery_client import govdelivery_status_map
from app.dao import notifications_dao
from app.errors import register_errors, InvalidRequest
from app.schema_validation import validate
from .govelivery_schema import govdelivery_webhook_schema

govdelivery_callback_blueprint = Blueprint("govdelivery_callback", __name__, url_prefix="/notifications/govdelivery")
register_errors(govdelivery_callback_blueprint)


@govdelivery_callback_blueprint.route('', methods=['POST'])
def process_govdelivery_response():
    try:
        data = validate(request.form, govdelivery_webhook_schema)
        sid = data['sid']
        reference = data['message_url'].split("/")[-1]
        govdelivery_status = data['status']
        notify_status = govdelivery_status_map[govdelivery_status]

    except ValidationError as e:
        raise e
    except Exception as e:
        raise InvalidRequest(f'Error processing Govdelivery callback: {e}', 400)

    else:
        try:
            notification = notifications_dao.dao_get_notification_by_reference(reference)

        except (MultipleResultsFound, NoResultFound) as e:
            exception_type = type(e).__name__
            current_app.logger.exception(
                f'Govdelivery callback with sid {sid} for reference {reference} '
                f'did not find exactly one notification: {exception_type}'
            )
            statsd_client.incr(f'callback.govdelivery.failure.{exception_type}')
        else:
            current_app.logger.info(
                f'Govdelivery callback for notification {notification.id} has status {govdelivery_status},'
                f' which maps to notification-api status {notify_status}'
            )
            if data.get('error_message'):
                current_app.logger.info(
                    f"Govdelivery error_message for notification {notification.id}: "
                    f"{data['error_message']}"
                )

            notifications_dao._update_notification_status(notification, notify_status)

            statsd_client.incr(f'callback.govdelivery.{notify_status}')

            if notification.sent_at:
                statsd_client.timing_with_dates(
                    'callback.govdelivery.elapsed-time', datetime.utcnow(), notification.sent_at)

    return jsonify(result='success'), 200
