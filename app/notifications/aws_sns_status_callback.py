from datetime import datetime
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from flask import current_app, request, jsonify
from http import HTTPStatus
from app import statsd_client
from app.schema_validation import validate
from app.schema_validation.definitions import uuid
from app.models import NOTIFICATION_FAILED, NOTIFICATION_SENT
from app.dao.notifications_dao import dao_get_notification_by_reference, _update_notification_status
from app.notifications.process_client_response import process_service_callback

SNS_STATUS_SUCCESS = "SUCCESS"
SNS_STATUS_FAILURE = "FAILURE"
SNS_STATUS_TYPES = [SNS_STATUS_SUCCESS, SNS_STATUS_FAILURE]

aws_sns_status_map = {
    SNS_STATUS_SUCCESS: NOTIFICATION_SENT,
    SNS_STATUS_FAILURE: NOTIFICATION_FAILED
}

sns_delivery_status_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "POST SNS delivery status",
    "type": "object",
    "title": "payload for POST /notifications/sms/sns",
    "properties": {
        "notification": {
            "type": "object",
            "properties": {
                "messageId": uuid,
                "timestamp": {"type": "string"}
            },
            "required": ["messageId"]
        },
        "delivery": {"type": "object"},
        "status": {"enum": SNS_STATUS_TYPES}
    },
    "required": ["status"]
}


def send_callback_metrics(notification):
    statsd_client.incr(f"callback.sns.{notification.status}")
    if notification.sent_at:
        statsd_client.timing_with_dates("callback.sns.elapsed-time", datetime.utcnow(), notification.sent_at)


def process_sns_delivery_status():
    callback = validate(request.get_json(), sns_delivery_status_schema)
    reference = callback['notification']['messageId']
    current_app.logger.debug(f"Full delivery response from AWS SNS for reference: {reference}\n{callback}")
    try:
        notification = dao_get_notification_by_reference(reference)
    except (NoResultFound, MultipleResultsFound) as e:
        current_app.logger.exception((
            f"AWS SNS delivery status callback for reference {reference} "
            f"did not find exactly one notification: {type(e)}"))
        return jsonify(result='error', message='Notification not found'), 404
    else:
        status = aws_sns_status_map.get(callback['status'])
        current_app.logger.info((
            f"AWS SNS delivery status callback for notification {notification.id} has status {callback['status']}"
            f", which maps to notification-api status {status}"))
        notification = _update_notification_status(notification, status)
        send_callback_metrics(notification)

        process_service_callback(notification)

    return jsonify({}), HTTPStatus.NO_CONTENT
