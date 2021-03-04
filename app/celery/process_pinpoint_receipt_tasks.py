import base64
import datetime
import json

import iso8601
from celery.exceptions import Retry
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound

from app import notify_celery, statsd_client
from app.config import QueueNames
from app.dao import notifications_dao
from app.feature_flags import FeatureFlag, is_feature_enabled
from app.models import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_PENDING,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE
)
from app.celery.service_callback_tasks import _check_and_queue_callback_task

_record_status_status_mapping = {
    'SUCCESSFUL': NOTIFICATION_SENDING,
    'DELIVERED': NOTIFICATION_DELIVERED,
    'PENDING': NOTIFICATION_SENDING,
    'INVALID': NOTIFICATION_TECHNICAL_FAILURE,
    'UNREACHABLE': NOTIFICATION_TEMPORARY_FAILURE,
    'UNKNOWN': NOTIFICATION_TEMPORARY_FAILURE,
    'BLOCKED': NOTIFICATION_PERMANENT_FAILURE,
    'CARRIER_UNREACHABLE': NOTIFICATION_TEMPORARY_FAILURE,
    'SPAM': NOTIFICATION_PERMANENT_FAILURE,
    'INVALID_MESSAGE': NOTIFICATION_TECHNICAL_FAILURE,
    'CARRIER_BLOCKED': NOTIFICATION_PERMANENT_FAILURE,
    'TTL_EXPIRED': NOTIFICATION_TEMPORARY_FAILURE,
    'MAX_PRICE_EXCEEDED': NOTIFICATION_PERMANENT_FAILURE
}


def event_type_is_optout(event_type, reference):
    is_optout = event_type == '_SMS.OPTOUT'

    if is_optout:
        current_app.logger.info(
            f"event type is OPTOUT for notification with reference {reference})"
        )
    return is_optout


def _map_record_status_to_notification_status(record_status):
    return _record_status_status_mapping[record_status]


@notify_celery.task(bind=True, name="process-pinpoint-result", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def process_pinpoint_results(self, response):
    if not is_feature_enabled(FeatureFlag.PINPOINT_RECEIPTS_ENABLED):
        current_app.logger.info('Pinpoint receipts toggle is disabled, skipping callback task')
        return True

    try:
        current_app.logger.info(f"pinpoint response is: {response}")
        pinpoint_message = json.loads(base64.b64decode(response['Message']))
        reference = pinpoint_message['attributes']['message_id']
        event_type = pinpoint_message.get('event_type')
        if event_type_is_optout(event_type, reference):
            return
        record_status = pinpoint_message['attributes']['record_status']
        notification_status = _map_record_status_to_notification_status(record_status)

        try:
            notification = notifications_dao.dao_get_notification_by_reference(reference)
        except NoResultFound:
            message_time = iso8601.parse_date(pinpoint_message['event_timestamp']).replace(tzinfo=None)
            if datetime.datetime.utcnow() - message_time < datetime.timedelta(minutes=5):
                self.retry(queue=QueueNames.RETRY)
            else:
                current_app.logger.warning(
                    f"notification not found for reference: {reference} (update to {notification_status})"
                )
            return

        if notification.status not in {NOTIFICATION_SENDING, NOTIFICATION_PENDING}:
            notifications_dao._duplicate_update_warning(notification, notification_status)
            return

        notifications_dao.update_notification_status_by_id(notification.id, notification_status)

        current_app.logger.info(
            f"PinPoint callback return status of {notification_status} for notification: {notification.id}"
        )

        statsd_client.incr(f"callback.pinpoint.{notification_status}")

        if notification.sent_at:
            statsd_client.timing_with_dates(
                'callback.pinpoint.elapsed-time', datetime.datetime.utcnow(), notification.sent_at)

        _check_and_queue_callback_task(notification)

        return True

    except Retry:
        raise

    except Exception as e:
        current_app.logger.exception(f"Error processing PinPoint results: {type(e)}")
        self.retry(queue=QueueNames.RETRY)
