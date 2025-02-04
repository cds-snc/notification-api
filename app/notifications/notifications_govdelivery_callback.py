from datetime import datetime
from dateutil import parser

from flask import Blueprint, current_app, jsonify, request
from jsonschema.exceptions import ValidationError
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound

from app import statsd_client
from app.clients.email.govdelivery_client import govdelivery_status_map
from app.dao import notifications_dao
from app.errors import register_errors, InvalidRequest
from app.schema_validation import validate
from .govelivery_schema import govdelivery_webhook_schema
from ..celery.service_callback_tasks import publish_complaint
from ..dao.complaint_dao import save_complaint
from ..models import Notification, Complaint

govdelivery_callback_blueprint = Blueprint('govdelivery_callback', __name__, url_prefix='/notifications/govdelivery')
register_errors(govdelivery_callback_blueprint)


@govdelivery_callback_blueprint.route('', methods=['POST'])
def process_govdelivery_response():
    try:
        data = validate(request.form, govdelivery_webhook_schema)
        sid = data['sid']
        reference = data['message_url'].split('/')[-1]
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
            current_app.logger.exception(
                'Govdelivery callback with sid %s for reference %s did not find exactly one notification.',
                sid,
                reference,
            )
            statsd_client.incr(f'callback.govdelivery.failure.{type(e).__name__}')
        else:
            current_app.logger.info(
                f'Govdelivery callback for notification {notification.id} has status {govdelivery_status},'
                f' which maps to notification-api status {notify_status}'
            )
            if data.get('error_message'):
                current_app.logger.info(
                    f'Govdelivery error_message for notification {notification.id}: {data["error_message"]}'
                )

            notifications_dao._update_notification_status(notification, notify_status)

            statsd_client.incr(f'callback.govdelivery.{notify_status}')

            if notification.sent_at:
                statsd_client.timing_with_dates(
                    'callback.govdelivery.elapsed-time', datetime.utcnow(), notification.sent_at
                )

            if govdelivery_status == 'blacklisted':
                complaint = create_complaint(data, notification)
                publish_complaint(complaint, notification, notification.to)

    return jsonify(result='success'), 200


def create_complaint(
    data: dict,
    notification: Notification,
) -> Complaint:
    current_app.logger.info(
        f'Govdelivery sent to blacklisted email. Creating complaint for notification {notification.id}'
    )

    complaint_date = data.get('completed_at', None)

    complaint = Complaint(
        notification_id=notification.id,
        service_id=notification.service_id,
        feedback_id=data['sid'],
        complaint_type=data['message_type'],
        complaint_date=parser.parse(complaint_date) if complaint_date else datetime.now(),
    )

    save_complaint(complaint)

    return complaint
