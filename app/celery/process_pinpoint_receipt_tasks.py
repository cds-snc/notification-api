import base64
import datetime
import json
from typing import Tuple

from celery.exceptions import Retry
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from app import notify_celery, statsd_client
from app.config import QueueNames
from app.dao.notifications_dao import update_notification_status_by_id, dao_get_notification_by_reference
from app.feature_flags import FeatureFlag, is_feature_enabled
from app.models import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT, Notification, NOTIFICATION_PREFERENCES_DECLINED
)
from app.celery.service_callback_tasks import check_and_queue_callback_task

FINAL_STATUS_STATES = [NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_TECHNICAL_FAILURE,
                       NOTIFICATION_PREFERENCES_DECLINED]

_record_status_status_mapping = {
    'SUCCESSFUL': NOTIFICATION_SENT,
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
    'MAX_PRICE_EXCEEDED': NOTIFICATION_TECHNICAL_FAILURE
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
        pinpoint_message = json.loads(base64.b64decode(response['Message']))
        reference = pinpoint_message['attributes']['message_id']
        event_type = pinpoint_message.get('event_type')
        record_status = pinpoint_message['attributes']['record_status']
        current_app.logger.info(
            f'received callback from Pinpoint with event_type of {event_type} and record_status of {record_status}'
            f' with reference {reference}'
        )
        notification_status = get_notification_status(event_type, record_status, reference)

        notification, should_retry, should_exit = attempt_to_get_notification(
            reference, notification_status, pinpoint_message['event_timestamp']
        )

        if should_retry:
            self.retry(queue=QueueNames.RETRY)

        if should_exit:
            return

        update_notification_status_by_id(notification.id, notification_status)

        current_app.logger.info(
            f"Pinpoint callback return status of {notification_status} for notification: {notification.id}"
        )

        statsd_client.incr(f"callback.pinpoint.{notification_status}")

        if notification.sent_at:
            statsd_client.timing_with_dates(
                'callback.pinpoint.elapsed-time', datetime.datetime.utcnow(), notification.sent_at)

        check_and_queue_callback_task(notification)

        return True

    except Retry:
        raise

    except Exception as e:
        current_app.logger.exception(f"Error processing Pinpoint results: {type(e)}")
        self.retry(queue=QueueNames.RETRY)


def get_notification_status(event_type: str, record_status: str, reference: str) -> str:
    if event_type_is_optout(event_type, reference):
        statsd_client.incr(f"callback.pinpoint.optout")
        notification_status = NOTIFICATION_PERMANENT_FAILURE
    else:
        notification_status = _map_record_status_to_notification_status(record_status)
    return notification_status


def attempt_to_get_notification(
        reference: str, notification_status: str, event_timestamp_in_ms: str
) -> Tuple[Notification, bool, bool]:
    should_retry = False
    notification = None

    try:
        notification = dao_get_notification_by_reference(reference)
        should_exit = check_notification_status(notification, notification_status)
    except NoResultFound:
        message_time = datetime.datetime.fromtimestamp(int(event_timestamp_in_ms) / 1000)
        if datetime.datetime.utcnow() - message_time < datetime.timedelta(minutes=5):
            should_retry = True
        else:
            current_app.logger.warning(
                f'notification not found for reference: {reference} (update to {notification_status})'
            )
        statsd_client.incr('callback.pinpoint.no_notification_found')
        should_exit = True
    except MultipleResultsFound:
        current_app.logger.warning(
            f'multiple notifications found for reference: {reference} (update to {notification_status})'
        )
        statsd_client.incr('callback.pinpoint.multiple_notifications_found')
        should_exit = True

    return notification, should_retry, should_exit


def check_notification_status(notification: Notification, notification_status: str) -> bool:
    should_exit = False
    # do not update if status has not changed
    if notification_status == notification.status:
        current_app.logger.info(
            f'Pinpoint callback received the same status of {notification_status} for'
            f' notification {notification_status})'
        )
        should_exit = True
    # do not update if notification status is in a final state
    if notification.status in FINAL_STATUS_STATES:
        log_notification_status_warning(notification, notification_status)
        should_exit = True
    return should_exit


def log_notification_status_warning(notification, status: str) -> None:
    time_diff = datetime.datetime.utcnow() - (notification.updated_at or notification.created_at)
    current_app.logger.warning(
        f'Invalid callback received. Notification id {notification.id} received a status update to {status}'
        f' {time_diff} after being set to {notification.status}. {notification.notification_type}'
        f' sent by {notification.sent_by}'
    )
