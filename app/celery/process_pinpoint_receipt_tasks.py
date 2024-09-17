import base64
import datetime
import json
from typing import Tuple

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from app import notify_celery
from app.celery.common import log_notification_total_time
from app.celery.exceptions import AutoRetryException
from app.dao.notifications_dao import (
    dao_get_notification_by_reference,
    dao_update_notification_by_id,
    duplicate_update_warning,
    update_notification_status_by_id,
    FINAL_STATUS_STATES,
)
from app.feature_flags import FeatureFlag, is_feature_enabled
from app.models import (
    Notification,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_PREFERENCES_DECLINED,
)
from app.celery.service_callback_tasks import check_and_queue_callback_task

# This is not an exhaustive list of all possible record statuses.  See the documentation linked below.
_record_status_status_mapping = {
    'SUCCESSFUL': NOTIFICATION_DELIVERED,
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
    'MAX_PRICE_EXCEEDED': NOTIFICATION_TECHNICAL_FAILURE,
    'OPTED_OUT': NOTIFICATION_PREFERENCES_DECLINED,
}


def _map_record_status_to_notification_status(record_status):
    if record_status not in _record_status_status_mapping:
        # This is a programming error, or Pinpoint's response format has changed.
        current_app.logger.critical('Unanticipated Pinpoint record status: %s', record_status)

    return _record_status_status_mapping.get(record_status, NOTIFICATION_TECHNICAL_FAILURE)


@notify_celery.task(
    bind=True,
    name='process-pinpoint-result',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=585,
    retry_backoff=True,
    retry_backoff_max=300,
)
@statsd(namespace='tasks')
def process_pinpoint_results(
    self,
    response,
):
    """
    Process a Pinpoint SMS stream event.  Messages long enough to require multiple segments only
    result in one event that contains the aggregate cost.

    Permissible event type and record status values are documented here:
        https://docs.aws.amazon.com/pinpoint/latest/developerguide/event-streams-data-sms.html

    An _SMS.OPTOUT event occurs when a veteran replies "STOP" to a text message.  An OPTED_OUT status occurs
    when Pinpoint receives input from Notify, but the Veteran has opted-out at the Pinpoint level.  This is
    different than Notify's communication item preferences.  If a veteran opts-out at that level, Pinpoint
    should never receive input trying to send a message to the opted-out veteran.
    """

    if not is_feature_enabled(FeatureFlag.PINPOINT_RECEIPTS_ENABLED):
        current_app.logger.info('Pinpoint receipts toggle is disabled.  Skipping callback task.')
        return True

    try:
        pinpoint_message = json.loads(base64.b64decode(response['Message']))
    except (json.decoder.JSONDecodeError, ValueError, TypeError, KeyError) as e:
        current_app.logger.exception(e)
        raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...')

    try:
        pinpoint_attributes = pinpoint_message['attributes']
        reference = pinpoint_attributes['message_id']
        event_type = pinpoint_message['event_type']
        record_status = pinpoint_attributes['record_status']
        number_of_message_parts = pinpoint_attributes['number_of_message_parts']
        price_in_millicents_usd = pinpoint_message['metrics']['price_in_millicents_usd']
    except KeyError as e:
        current_app.logger.error('The event stream message data is missing expected attributes.')
        current_app.logger.exception(e)
        current_app.logger.debug(pinpoint_message)
        raise AutoRetryException('Found KeyError, autoretrying...')

    current_app.logger.info(
        'Processing Pinpoint result. | reference=%s | event_type=%s | record_status=%s | '
        'number_of_message_parts=%s | price_in_millicents_usd=%s',
        reference,
        event_type,
        record_status,
        number_of_message_parts,
        price_in_millicents_usd,
    )

    try:
        notification_status = get_notification_status(event_type, record_status, reference)

        notification, should_exit = attempt_to_get_notification(
            reference, notification_status, pinpoint_message['event_timestamp']
        )

        if should_exit:
            return

        assert notification is not None

        if notification_status == NOTIFICATION_PREFERENCES_DECLINED:
            if event_type == '_SMS.OPTOUT':
                notification.status_reason = 'The veteran responded with STOP.'
            elif record_status == 'OPTED_OUT':
                notification.status_reason = 'The veteran is opted-out at the Pinpoint level.'

        if price_in_millicents_usd > 0.0:
            dao_update_notification_by_id(
                notification_id=notification.id,
                status=notification_status,
                segments_count=number_of_message_parts,
                cost_in_millicents=price_in_millicents_usd,
            )
        else:
            update_notification_status_by_id(
                notification_id=notification.id, status=notification_status, status_reason=notification.status_reason
            )

        current_app.logger.info(
            'Pinpoint callback return status of %s for notification: %s',
            notification_status,
            notification.id,
        )

        log_notification_total_time(
            notification.id,
            notification.created_at,
            notification_status,
            'pinpoint',
        )

        check_and_queue_callback_task(notification)

        return True
    except Exception as e:
        current_app.logger.exception(e)
        raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...')


def get_notification_status(
    event_type: str,
    record_status: str,
    reference: str,
) -> str:
    if event_type == '_SMS.OPTOUT':
        # The veteran replied "STOP".
        current_app.logger.info('event type is OPTOUT for notification with reference %s', reference)
        notification_status = NOTIFICATION_PREFERENCES_DECLINED
    else:
        notification_status = _map_record_status_to_notification_status(record_status)
    return notification_status


def attempt_to_get_notification(
    reference: str, notification_status: str, event_timestamp_in_ms: str
) -> Tuple[Notification, bool, bool]:
    notification = None

    try:
        notification = dao_get_notification_by_reference(reference)
        should_exit = check_notification_status(notification, notification_status)
    except NoResultFound:
        # A race condition exists wherein a callback might be received before a notification
        # persists in the database.  Continue retrying for up to 5 minutes (300 seconds).
        should_exit = True
        message_time = datetime.datetime.fromtimestamp(int(event_timestamp_in_ms) / 1000)
        if datetime.datetime.utcnow() - message_time < datetime.timedelta(minutes=5):
            current_app.logger.info(
                'Pinpoint callback event for reference %s was received less than five minutes ago.', reference
            )
            raise AutoRetryException('Found NoResultFound, autoretrying...')
        else:
            current_app.logger.critical(
                'notification not found for reference: %s (update to %s)', reference, notification_status
            )
    except MultipleResultsFound:
        current_app.logger.warning(
            'multiple notifications found for reference: %s (update to %s)', reference, notification_status
        )
        should_exit = True

    return notification, should_exit


def check_notification_status(notification: Notification, notification_status: str) -> bool:
    """
    Check if the notification status should be updated. If the status has not changed, or if the status is in a final
    state, do not update the notification. *Unless* the status is being updated to delivered from a different final
    status, in which case, the notification should always be updated.

    Args:
        notification (Notification): The notification to check.
        notification_status (str): The status to update the notification to.

    Returns:
        bool: False if the notification status should not be updated, True if the downstream task should exit.
    """
    should_exit = False

    # Do not update if the status has not changed.
    if notification_status == notification.status:
        current_app.logger.info(
            'Pinpoint callback received the same status of %s for notification %s)',
            notification_status,
            notification_status,
        )
        should_exit = True
    elif notification_status == NOTIFICATION_DELIVERED:
        # ensure the notification is updated to delivered whenever we receive a delivered status
        should_exit = False
    elif notification.status in FINAL_STATUS_STATES:
        # Do not update if notification status is in a final state.
        duplicate_update_warning(notification, notification_status)
        should_exit = True

    return should_exit
