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
from app.dao.notifications_dao import (
    dao_get_notification_by_reference,
    dao_update_notification,
    update_notification_status_by_id,
)
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


def _map_record_status_to_notification_status(record_status):
    return _record_status_status_mapping[record_status]


@notify_celery.task(bind=True, name="process-pinpoint-result", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def process_pinpoint_results(self, response):
    """
    Process a Pinpoint SMS stream event.  Messages long enough to require multiple segments only
    result in one event that contains the aggregate cost.

    https://docs.aws.amazon.com/pinpoint/latest/developerguide/event-streams-data-sms.html
    """

    if not is_feature_enabled(FeatureFlag.PINPOINT_RECEIPTS_ENABLED):
        current_app.logger.info('Pinpoint receipts toggle is disabled.  Skipping callback task.')
        return True

    try:
        pinpoint_message = json.loads(base64.b64decode(response['Message']))
    except (json.decoder.JSONDecodeError, ValueError, TypeError, KeyError) as e:
        current_app.logger.exception(e)
        self.retry(queue=QueueNames.RETRY)
        return None

    try:
        pinpoint_attributes = pinpoint_message["attributes"]
        reference = pinpoint_attributes["message_id"]
        event_type = pinpoint_message["event_type"]
        record_status = pinpoint_attributes["record_status"]
        number_of_message_parts = pinpoint_attributes["number_of_message_parts"]
        price_in_millicents_usd = pinpoint_message["metrics"]["price_in_millicents_usd"]
    except KeyError as e:
        current_app.logger.error("The event stream message data is missing expected attributes.")
        current_app.logger.exception(e)
        current_app.logger.debug(pinpoint_message)
        self.retry(queue=QueueNames.RETRY)
        return None

    current_app.logger.info(
        "Processing Pinpoint result. | reference=%s | event_type=%s | record_status=%s | "
        "number_of_message_parts=%s | price_in_millicents_usd=%s",
        reference, event_type, record_status, number_of_message_parts, price_in_millicents_usd
    )

    try:
        notification_status = get_notification_status(event_type, record_status, reference)

        notification, should_retry, should_exit = attempt_to_get_notification(
            reference, notification_status, pinpoint_message['event_timestamp']
        )

        if should_retry:
            self.retry(queue=QueueNames.RETRY)

        if should_exit:
            return

        assert notification is not None

        if price_in_millicents_usd > 0.0:
            notification.status = notification_status
            notification.segments_count = number_of_message_parts
            notification.cost_in_millicents = price_in_millicents_usd
            dao_update_notification(notification)
        else:
            update_notification_status_by_id(
                notification_id=notification.id,
                status=notification_status
            )

        current_app.logger.info(
            "Pinpoint callback return status of %s for notification: %s",
            notification_status, notification.id
        )

        statsd_client.incr(f"callback.pinpoint.{notification_status}")

        if notification.sent_at:
            statsd_client.timing_with_dates(
                'callback.pinpoint.elapsed-time', datetime.datetime.utcnow(), notification.sent_at)

        check_and_queue_callback_task(notification)

        return True

    except Retry:
        # This block exists to preempt executing the "Exception" logic below.  A better approach is
        # to catch specific exceptions where they might occur.
        raise
    except Exception as e:
        current_app.logger.exception(e)
        self.retry(queue=QueueNames.RETRY)

    return None


def get_notification_status(event_type: str, record_status: str, reference: str) -> str:
    if event_type == '_SMS.OPTOUT':
        current_app.logger.info("event type is OPTOUT for notification with reference %s", reference)
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
        # A race condition exists wherein a callback might be received before a notification
        # persists in the database.  Continue retrying for up to 5 minutes (300 seconds).
        message_time = datetime.datetime.fromtimestamp(int(event_timestamp_in_ms) / 1000)
        if datetime.datetime.utcnow() - message_time < datetime.timedelta(minutes=5):
            current_app.logger.info(
                'Pinpoint callback event for reference %s was received less than five minutes ago.', reference
            )
            should_retry = True
        else:
            current_app.logger.critical(
                'notification not found for reference: %s (update to %s)', reference, notification_status
            )
        statsd_client.incr('callback.pinpoint.no_notification_found')
        should_exit = True
    except MultipleResultsFound:
        current_app.logger.warning(
            'multiple notifications found for reference: %s (update to %s)', reference, notification_status
        )
        statsd_client.incr('callback.pinpoint.multiple_notifications_found')
        should_exit = True

    return notification, should_retry, should_exit


def check_notification_status(notification: Notification, notification_status: str) -> bool:
    # Do not update if the status has not changed.
    if notification_status == notification.status:
        current_app.logger.info(
            'Pinpoint callback received the same status of %s for notification %s)',
            notification_status, notification_status
        )
        return True

    # Do not update if notification status is in a final state.
    if notification.status in FINAL_STATUS_STATES:
        log_notification_status_warning(notification, notification_status)
        return True

    return False


def log_notification_status_warning(notification, status: str) -> None:
    time_diff = datetime.datetime.utcnow() - (notification.updated_at or notification.created_at)
    current_app.logger.warning(
        'Invalid callback received. Notification id %s received a status update to %s '
        '%s after being set to %s. %s sent by %s',
        notification.id, status, time_diff, notification.status, notification.notification_type, notification.sent_by
    )
