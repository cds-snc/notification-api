import datetime
import random
from typing import Tuple

from app.celery.process_ses_receipts_tasks import check_and_queue_va_profile_notification_status_callback
from celery import Task
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from app import clients, notify_celery, redis_store, statsd_client
from app.celery.common import log_notification_total_time
from app.celery.exceptions import AutoRetryException, NonRetryableException
from app.celery.process_pinpoint_inbound_sms import CeleryEvent
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.clients.sms import SmsClient, SmsStatusRecord, UNABLE_TO_TRANSLATE
from app.constants import (
    CARRIER_SMS_MAX_RETRIES,
    CARRIER_SMS_MAX_RETRY_WINDOW,
    DELIVERY_STATUS_CALLBACK_TYPE,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENDING,
    STATUS_REASON_UNDELIVERABLE,
)
from app.dao.notifications_dao import (
    dao_get_notification_by_reference,
    dao_update_sms_notification_delivery_status,
    dao_update_sms_notification_status_to_created_for_retry,
)
from app.dao.service_callback_dao import dao_get_callback_include_payload_status
from app.models import Notification


# Create SQS Queue for Process Deliver Status.
@notify_celery.task(
    bind=True,
    name='process-delivery-status-result',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=585,
    retry_backoff=True,
    retry_backoff_max=300,
)
@statsd(namespace='tasks')
def process_delivery_status(
    self: Task,
    event: CeleryEvent,
) -> None:
    """
    This is a Celery task for updating the delivery status of a Twilio notification.
    """

    current_app.logger.debug('twilio incoming sms update: %s', event)

    try:
        sqs_message = _get_sqs_message(event)
        current_app.logger.debug('twilio decoded sms update: %s', sqs_message)
        provider_name, provider = _get_provider_info(sqs_message)
    except NonRetryableException:
        statsd_client.incr('clients.sms.twilio.status_update.error')
        raise

    notification_platform_status: SmsStatusRecord = get_notification_platform_status(
        provider, sqs_message.get('body', '')
    )

    current_app.logger.info(
        'Processing %s result.  | reference: %s | notification_status: %s | '
        'message_parts: %s | price_millicents: %s | provider_updated_at: %s',
        provider_name,
        notification_platform_status.reference,
        notification_platform_status.status,
        notification_platform_status.message_parts,
        notification_platform_status.price_millicents,
        notification_platform_status.provider_updated_at,
    )
    sms_status_update(notification_platform_status, event_in_seconds=(self.request.retries * self.default_retry_delay))


def get_notification_platform_status(
    provider: SmsClient,
    body: str | dict[str, str],
) -> SmsStatusRecord:
    """Performs a translation on the body"""

    try:
        notification_platform_status: SmsStatusRecord = provider.translate_delivery_status(body)
    except (ValueError, KeyError) as e:
        current_app.logger.exception('The event message data is missing expected attributes: %s', body)
        statsd_client.incr(f'clients.sms.{provider}.status_update.error')
        raise NonRetryableException(f'Found {type(e).__name__}, {UNABLE_TO_TRANSLATE}')

    current_app.logger.debug('retrieved delivery status: %s', notification_platform_status)

    return notification_platform_status


def _get_include_payload_status(
    notification: Notification,
) -> bool:
    """Determines whether payload should be included in delivery status callback data"""
    include_payload_status = False
    current_app.logger.info('Determine if payload should be included')
    # this was updated to no longer need the "No Result Found" exception

    try:
        include_payload_status = dao_get_callback_include_payload_status(
            notification.service_id, DELIVERY_STATUS_CALLBACK_TYPE
        )

    except (AttributeError, TypeError):
        current_app.logger.exception(
            'Could not determine include_payload property for ServiceCallback and notification: %s', notification.id
        )

    return include_payload_status


def _get_sqs_message(event: CeleryEvent) -> dict:
    """Gets the sms message from the CeleryEvent"""
    sqs_message = event.get('message')
    if sqs_message is None:
        # Logic was previously setup this way. Not sure why we're retrying on type/key errors
        current_app.logger.error('Unable to parse event format for event: %s', event)
        raise NonRetryableException(f'Unable to find "message" in event, {UNABLE_TO_TRANSLATE}')
    return sqs_message


def _get_provider_info(sqs_message: dict) -> Tuple[str, any]:
    """Gets the provider_name and provider object"""
    provider_name = sqs_message.get('provider')
    provider = clients.get_sms_client(provider_name)

    # provider cannot None
    if provider is None:
        current_app.logger.warning('Unable to find provider given the following message: %s', sqs_message)
        raise NonRetryableException(f'Found no provider, {UNABLE_TO_TRANSLATE}')

    return provider_name, provider


def _get_notification(
    reference: str,
    provider: str,
    event_timestamp_in_ms: str | None,
    event_time_in_seconds: int,
) -> Notification:
    """Get the notification by reference.

    Raise a retryable exception if it could not be found and the event happened within 5 minutes of the creation date.

    Args:
        reference (str): The provider reference
        provider (str): The provider being used
        event_timestamp_in_ms (str | None): Timestamp the event came in
        event_time_in_seconds (int): How many seconds it has retried

    Raises:
        AutoRetryException: Possible race condition, retry
        NonRetryableException: No notification found
        NonRetryableException: Multiple notifications found

    Returns:
        Notification: A Notification object
    """

    def log_and_retry():
        current_app.logger.info(
            '%s callback event for reference %s was received less than five minutes ago.', provider, reference
        )
        statsd_client.incr(f'clients.sms.{provider}.status_update.retry')
        raise AutoRetryException('Found NoResultFound, autoretrying...')

    def log_and_fail(reason: str):
        current_app.logger.exception('%s: %s', reason, reference)
        statsd_client.incr(f'clients.sms.{provider}.status_update.error')
        raise NonRetryableException(reason)

    try:
        notification = dao_get_notification_by_reference(reference)
    except NoResultFound:
        # A race condition exists wherein a callback might be received before a notification
        # persists in the database.  Continue retrying for up to 5 minutes (300 seconds).
        if event_timestamp_in_ms:
            # Do the conversion and check if it happened within the last 5 minutes
            message_time = datetime.datetime.fromtimestamp(int(event_timestamp_in_ms) / 1000)
            if datetime.datetime.utcnow() - message_time < datetime.timedelta(minutes=5):
                log_and_retry()
            else:
                log_and_fail('Notification not found')
        elif event_time_in_seconds < 300:
            # If it happened within the last 5 minutes
            log_and_retry()
        else:
            log_and_fail('Notification not found')
    except MultipleResultsFound:
        log_and_fail('Multiple notifications found')

    return notification


def sms_status_update(
    sms_status: SmsStatusRecord,
    event_timestamp: str | None = None,
    event_in_seconds: int = 300,  # Don't retry by default
) -> None:
    """Get and update a notification.

    Args:
        sms_status (SmsStatusRecord): The status record update
        event_timestamp (str | None, optional): Timestamp the Pinpoint event came in. Defaults to None.
        event_in_seconds (int, optional): How many seconds Twilio updates have retried. Defaults to 300

    Raises:
        NonRetryableException: Unable to update the notification
    """
    notification = _get_notification(sms_status.reference, sms_status.provider, event_timestamp, event_in_seconds)
    last_updated_at = notification.updated_at

    current_app.logger.info(
        'Initial %s logic | reference: %s | notification_id: %s | status: %s | status_reason: %s',
        sms_status.provider,
        sms_status.reference,
        notification.id,
        sms_status.status,
        sms_status.status_reason,
    )

    # Never include a status reason for a delivered notification.
    if sms_status.status == NOTIFICATION_DELIVERED:
        sms_status.status_reason = None

    try:
        notification: Notification = dao_update_sms_notification_delivery_status(
            notification_id=notification.id,
            notification_type=notification.notification_type,
            new_status=sms_status.status,
            new_status_reason=sms_status.status_reason,
            segments_count=sms_status.message_parts,
            cost_in_millicents=sms_status.price_millicents + notification.cost_in_millicents,
        )
        statsd_client.incr(f'clients.sms.{sms_status.provider}.delivery.status.{sms_status.status}')
    except Exception:
        statsd_client.incr(f'clients.sms.{sms_status.provider}.status_update.error')
        raise NonRetryableException('Unable to update notification')

    current_app.logger.info(
        'Final %s logic | reference: %s | notification_id: %s | status: %s | status_reason: %s | cost_in_millicents: %s',
        sms_status.provider,
        sms_status.reference,
        notification.id,
        notification.status,
        notification.status_reason,
        notification.cost_in_millicents,
    )

    log_notification_total_time(
        notification.id,
        notification.created_at,
        sms_status.status,
        sms_status.provider,
        sms_status.provider_updated_at,
    )

    # Our clients are not prepared to deal with pinpoint payloads
    if not _get_include_payload_status(notification):
        sms_status.payload = None

    try:
        # Only send if there was an update
        if last_updated_at != notification.updated_at:
            check_and_queue_callback_task(notification, sms_status.payload)
            check_and_queue_va_profile_notification_status_callback(notification)
        statsd_client.incr(f'clients.sms.{sms_status.provider}.status_update.success')
    except Exception:
        current_app.logger.exception('Failed to check_and_queue_callback_task for notification: %s', notification.id)
        statsd_client.incr(f'clients.sms.{sms_status.provider}.status_update.error')


def can_retry_sms_request(
    status: str,
    retries: int,
    max_retries: int,
    sent_at: datetime,
    retry_window: datetime.timedelta,
) -> bool:
    """Determine if a retry is allowed.

    Determine if a retry is allowed based on the status, number of retries,
    the maximum retries allowed, the time the message was sent, and
    the retry window.

    Parameters:
        status (str): Current notification status.
        retries (int): The number of retries already attempted.
        max_retries (int): The maximum number of retries allowed.
        sent_at (datetime): The timestamp when the message was initially sent.
        retry_window (timedelta): The allowable time window for retries.

    Returns:
        bool: True if retrying is allowed, False otherwise.
    """
    # Calculate the time elapsed since the message was sent
    time_elapsed = datetime.datetime.utcnow() - sent_at

    return (
        (retries is not None)
        and (status == NOTIFICATION_SENDING)
        and (retries <= max_retries)
        and (time_elapsed < retry_window)
    )


def get_sms_retry_delay(retry_count: int) -> int:
    """Calculate the retry delay for SMS delivery with random jitter.

    Delays were chosen to cover transient errors and small scale service disruptions

    Note: Delays limited to under 900s due to AWS SQS limitation

    Assumes up to 2 retries, repeating final delay for subsequent:
    1st retry: 60 seconds +/- 10%
    2nd retry: 10 minutes (600 seconds) +/- 10%

    Parameters:
        retry_count (int): The retry attempt number.

    Returns:
        int: Delay in seconds with applied jitter.
    """
    delay_with_jitter_by_retry_count = {
        1: (60, 6),  # 60 seconds +/- 6 seconds (10%)
        2: (600, 60),  # 10 minutes +/- 60 seconds (10%)
    }

    # Safeguard against retry counts outside the defined range
    # Default to largest delay
    default_delay_with_jitter = (600, 60)

    base_delay, jitter_range = delay_with_jitter_by_retry_count.get(retry_count, default_delay_with_jitter)

    # Apply jitter
    return int(base_delay + random.randint(-jitter_range, jitter_range))  # nosec non-cryptographic use case


def update_sms_retry_count(
    notification_retry_id: str,
    initial_value: int = 0,
    ttl: int | None = None,
) -> int:
    """Get updated retry count for this notification from redis store, initializing pre-increment initial value if it doesn't exist

    Args:
        notification_retry_id (str): The value to retrieve from redis.
        initial_value (int): The initial value to set if the key doesn't exist.
        ttl (int, optional): Time-to-live for the value, in seconds.

    Returns:
        int: The current retry count

    Raises:
        ValueError: Unable to retrieve from redis
    """

    try:
        # Set the initial value only if the value does not exist
        redis_store.set(notification_retry_id, initial_value, ex=ttl, nx=True)
        value = redis_store.incr(notification_retry_id)
    except (ValueError, TypeError):
        raise ValueError(
            f"Expected an integer value for id '{notification_retry_id}', but got: {value} (type: {type(value)})"
        )
    except BaseException:
        # base redis exception already logged in redis client
        raise Exception('Unable to retrieve value from redis.')

    return int(value)


def mark_retry_as_permanent_failure(notification: Notification, sms_status: SmsStatusRecord):
    """Mark retry as permanent failure and attempt callbacks.

    Args:
        notfication (Notification): The notification that is not eligible for further retires
        sms_status (SmsStatusRecord): The status record update

    Raises:
        NonRetryableException: Unable update the notification
    """
    # mark as permanant failure so client can be updated
    sms_status.status = NOTIFICATION_PERMANENT_FAILURE
    sms_status.status_reason = STATUS_REASON_UNDELIVERABLE

    # avoid an out-of-order double billing, previous permanent_failure or delivered already counted
    # temporary_failure not possible with retry handling
    if notification.status != NOTIFICATION_SENDING:
        sms_status.price_millicents = 0

    try:
        notification: Notification = dao_update_sms_notification_delivery_status(
            notification_id=notification.id,
            notification_type=notification.notification_type,
            new_status=sms_status.status,
            new_status_reason=sms_status.status_reason,
            segments_count=sms_status.message_parts,
            cost_in_millicents=sms_status.price_millicents + notification.cost_in_millicents,
        )
        statsd_client.incr(f'clients.sms.{sms_status.provider}.delivery.status.{sms_status.status}')
    except Exception:
        statsd_client.incr(f'clients.sms.{sms_status.provider}.status_update.error')
        raise NonRetryableException('Unable to update notification')

    current_app.logger.info(
        'Final %s logic | reference: %s | notification_id: %s | status: %s | status_reason: %s | cost_in_millicents: %s',
        sms_status.provider,
        sms_status.reference,
        notification.id,
        notification.status,
        notification.status_reason,
        notification.cost_in_millicents,
    )

    # Our clients are not prepared to deal with pinpoint payloads
    if not _get_include_payload_status(notification):
        sms_status.payload = None

    try:
        check_and_queue_callback_task(notification, sms_status.payload)
    except Exception:
        current_app.logger.exception('Failed check_and_queue_callback_task for notification: %s', notification.id)
        statsd_client.incr(f'clients.sms.{sms_status.provider}.status_update.error')
    else:
        try:
            check_and_queue_va_profile_notification_status_callback(notification)
            statsd_client.incr(f'clients.sms.{sms_status.provider}.status_update.success')
        except Exception:
            current_app.logger.exception(
                'Failed check_and_queue_va_profile_notification_status_callback for notification: %s',
                notification.id,
            )
            statsd_client.incr(f'clients.sms.{sms_status.provider}.status_update.error')


def sms_attempt_retry(
    sms_status: SmsStatusRecord,
    event_timestamp: str | None = None,
    event_in_seconds: int = 300,  # Don't retry _get_notification by default
):
    """Attempt retry sending notification.

    Retry notification if within permissible limits and update notification.
    If retry limit or retry window exceeded call sms_status_update with STATUS_REASON_UNDELIVERABLE

    Args:
        sms_status (SmsStatusRecord): The status record update
        event_timestamp (str | None, optional): Timestamp the Pinpoint event came in. Defaults to None.
        event_in_seconds (int, optional): How long since initial event. Defaults to 300

    Raises:
        NonRetryableException: Unable to update SMS retry count or update the notification
    """

    # avoid circular import
    from app.notifications.process_notifications import send_notification_to_queue_delayed

    notification = _get_notification(sms_status.reference, sms_status.provider, event_timestamp, event_in_seconds)

    current_app.logger.info(
        'Entering %s retryable failure logic to process event | reference: %s | notification_id: %s | current_status: %s | current_status_reason: %s | event_sms_status: %s | event_sms_status_reason: %s',
        sms_status.provider,
        sms_status.reference,
        notification.id,
        notification.status,
        notification.status_reason,
        sms_status.status,
        sms_status.status_reason,
    )

    notification_retry_id = f'notification-carrier-sms-retry-count-{notification.id}'
    retry_count_redis_ttl = int(CARRIER_SMS_MAX_RETRY_WINDOW.total_seconds())

    try:
        retry_count = update_sms_retry_count(notification_retry_id, ttl=retry_count_redis_ttl)
    except Exception:
        current_app.logger.error('Unable to retrieve value from Redis')
        retry_count = None

    if can_retry_sms_request(
        notification.status, retry_count, CARRIER_SMS_MAX_RETRIES, notification.sent_at, CARRIER_SMS_MAX_RETRY_WINDOW
    ):
        retry_delay = get_sms_retry_delay(retry_count)

        # need to roll notification status back to 'created' for requeue to work
        # reference is also cleared to avoid race conditions while being requeued
        try:
            notification: Notification = dao_update_sms_notification_status_to_created_for_retry(
                notification_id=notification.id,
                notification_type=notification.notification_type,
                cost_in_millicents=notification.cost_in_millicents + sms_status.price_millicents,
                segments_count=sms_status.message_parts,
            )
        except Exception:
            statsd_client.incr(f'clients.sms.{sms_status.provider}.status_update.error')
            raise NonRetryableException('Unable to update notification')

        current_app.logger.info(
            'Notification updated prior to requeue attempt | notification_id: %s | notification_status: %s | cost_in_milicents %s',
            notification.id,
            notification.status,
            notification.cost_in_millicents,
        )
        statsd_client.incr(f'clients.sms.{sms_status.provider}.delivery.status.{sms_status.status}')

        current_app.logger.info(
            'Attempting %s requeue | notification_id: %s | retry_delay: %s seconds | retry_count: %s',
            sms_status.provider,
            notification.id,
            retry_delay,
            retry_count,
        )

        try:
            send_notification_to_queue_delayed(
                notification,
                notification.service.research_mode,
                sms_sender_id=notification.sms_sender_id,
                delay_seconds=retry_delay,
            )
        except Exception:
            raise NonRetryableException('Unable to queue notification for delivery retry')

        current_app.logger.info(
            'Requeued notification for delayed %s delivery | notification_id: %s | retry_delay: %s seconds',
            sms_status.provider,
            notification.id,
            retry_delay,
        )
    else:
        mark_retry_as_permanent_failure(notification, sms_status)
