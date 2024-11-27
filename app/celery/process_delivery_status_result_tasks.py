import datetime
from typing import Tuple

from celery import Task
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from app import notify_celery, statsd_client, clients
from app.celery.common import log_notification_total_time
from app.celery.exceptions import AutoRetryException, NonRetryableException
from app.celery.process_pinpoint_inbound_sms import CeleryEvent
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.clients.sms import SmsClient, SmsStatusRecord, UNABLE_TO_TRANSLATE
from app.constants import DELIVERY_STATUS_CALLBACK_TYPE, NOTIFICATION_DELIVERED
from app.dao.notifications_dao import (
    dao_get_notification_by_reference,
    dao_update_sms_notification_delivery_status,
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
            cost_in_millicents=sms_status.price_millicents,
        )
        statsd_client.incr(f'clients.sms.{sms_status.provider}.delivery.status.{sms_status.status}')
    except Exception:
        statsd_client.incr(f'clients.sms.{sms_status.provider}.status_update.error')
        raise NonRetryableException('Unable to update notification')

    current_app.logger.info(
        'Final %s logic | reference: %s | notification_id: %s | status: %s | status_reason: %s',
        sms_status.provider,
        sms_status.reference,
        notification.id,
        notification.status,
        notification.status_reason,
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
        statsd_client.incr(f'clients.sms.{sms_status.provider}.status_update.success')
    except Exception:
        current_app.logger.exception('Failed to check_and_queue_callback_task for notification: %s', notification.id)
        statsd_client.incr(f'clients.sms.{sms_status.provider}.status_update.error')
