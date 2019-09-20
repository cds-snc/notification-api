from datetime import datetime

from flask import Blueprint
from flask import current_app
from flask import json
from flask import request, jsonify

from app.errors import InvalidRequest, register_errors
from app.clients.email.sendgrid_client import get_sendgrid_responses
from app import statsd_client
from app.dao import notifications_dao

email_callback_blueprint = Blueprint("email_callback", __name__, url_prefix="/notifications/email")
register_errors(email_callback_blueprint)


@email_callback_blueprint.route('/sendgrid', methods=['POST'])
def process_sendgrid_response():
    data = json.loads(request.data)
    try:

        for obj in data:

            notification_status = get_sendgrid_responses(obj["event"])
            reference = obj['sg_message_id'].split(".")[0]

            notification = notifications_dao.dao_get_notification_by_reference(reference)

            notifications_dao._update_notification_status(notification=notification, status=notification_status)

            current_app.logger.info('SendGird callback return status of {} for notification: {}'.format(
                notification_status, notification.id
            ))

            statsd_client.incr('callback.sendgrid.{}'.format(notification_status))

            if notification.sent_at:
                statsd_client.timing_with_dates(
                    'callback.sendgrid.elapsed-time', datetime.utcnow(), notification.sent_at)

    except Exception as e:
        current_app.logger.exception('Error processing SendGrid results: {}'.format(type(e)))
        raise InvalidRequest(message="Error processing SendGrid results", status_code=400)
    else:
        return jsonify(result='success'), 200
