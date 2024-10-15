from app.models import DELIVERY_STATUS_CALLBACK_TYPE, NOTIFICATION_DELIVERED
from app.celery.common import log_notification_total_time
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.celery.process_pinpoint_inbound_sms import CeleryEvent
from app.clients.sms import SmsStatusRecord
from app.dao.notifications_dao import (
    dao_get_notification_by_reference,
    dao_update_notification_by_id,
    update_notification_delivery_status,
)

from typing import Tuple
from flask import current_app

from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from app import notify_celery, statsd_client, clients
from app.celery.exceptions import AutoRetryException
from app.dao.service_callback_dao import dao_get_callback_include_payload_status
from app.dao.notifications_dao import duplicate_update_warning

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
    self,
    event: CeleryEvent,
) -> bool:
    """
    This is a Celery task for updating the delivery status of a notification.
    """

    # preset variables to address "unbounded local variable"
    sqs_message = None
    notification_platform_status = None

    current_app.logger.info('processing delivery status')
    current_app.logger.debug(event)

    # first attempt to process the incoming event
    sqs_message = _get_sqs_message(event)

    # get the provider
    (provider_name, provider) = _get_provider_info(sqs_message)

    body = sqs_message.get('body')
    current_app.logger.info('retrieved delivery status body: %s', body)

    # get notification_platform_status
    notification_platform_status: SmsStatusRecord = _get_notification_platform_status(self, provider, body, sqs_message)
    current_app.logger.info(
        'Processing Notification Delivery Status. | reference=%s | notification_status=%s | '
        'number_of_message_parts=%s | price_in_millicents_usd=%s',
        notification_platform_status.reference,
        notification_platform_status.status,
        notification_platform_status.message_parts,
        notification_platform_status.price_millicents,
    )

    # Retrieve the inbound message for this provider.  We are updating the status of the outbound message.
    notification, should_exit = attempt_to_get_notification(
        notification_platform_status.reference,
        notification_platform_status.status,
        self.request.retries * self.default_retry_delay,
    )

    if should_exit:
        current_app.logger.warning(
            'Updating notification: %s resulted in should_exit - event: %s',
            notification.id if notification is not None else f'{notification_platform_status.reference} (aws ref)',
            event,
        )
        return False

    try:
        # calculate pricing
        current_app.logger.info(
            'Calculate Pricing: %s and update notification_status: %s with number_of_message_parts: %s for notification: %s',
            provider_name,
            notification_platform_status.status,
            notification_platform_status.message_parts,
            getattr(notification, 'id', 'unknown'),
        )

        _calculate_pricing_and_update_notification(
            notification_platform_status.price_millicents,
            notification,
            notification_platform_status.status,
            notification_platform_status.message_parts,
            notification_platform_status.status_reason,
        )

        current_app.logger.info(
            '%s callback return status of %s for notification: %s',
            provider_name,
            notification_platform_status.status,
            notification.id,
        )

        log_notification_total_time(
            notification.id,
            notification.created_at,
            notification_platform_status.status,
            provider_name,
        )

        # check if payload is to be include in cardinal set in the service callback is (service_id, callback_type)
        if not _get_include_payload_status(self, notification):
            notification_platform_status.payload = {}
        check_and_queue_callback_task(notification, notification_platform_status.payload)
        return True
    except Exception as e:
        # why are we here logging.warning indicate the step that was being performed
        current_app.logger.exception(e)
        raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...')


def attempt_to_get_notification(
    reference: str, notification_status: str, event_duration_in_seconds: int
) -> Tuple[Notification, bool]:
    """
    Attempt to get the Notification object, and determine whether the Celery Event should be retried or exit.
    """

    notification = None
    should_exit = False
    try:
        notification = dao_get_notification_by_reference(reference)
        should_exit = check_notification_status(notification, notification_status)
        current_app.logger.info(
            'Delivery Status callback return status of %s for notification:  %s', notification_status, notification.id
        )
    except NoResultFound:
        # A race condition exists wherein a callback might be received before a notification
        # persists in the database.  Continue retrying for up to 5 minutes (300 seconds).
        statsd_client.incr('callback.delivery_status.no_notification_found')
        should_exit = True
        if event_duration_in_seconds < 300:
            current_app.logger.info(
                'Delivery Status callback event for reference %s was received less than five minutes ago.', reference
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
        statsd_client.incr('callback.delivery_status.multiple_notifications_found')
        should_exit = True

    return notification, should_exit


def check_notification_status(
    notification: Notification,
    notification_status: str,
) -> bool:
    """Check if the SQS callback received the same status as the notification reports"""
    # Do not update if the status has not changed.
    if notification_status == notification.status:
        current_app.logger.info(
            'SQS callback received the same status of %s for notification %s', notification_status, notification.id
        )
        return True

    # Do not update if notification status is already delivered
    if notification.status == NOTIFICATION_DELIVERED:
        duplicate_update_warning(notification, notification_status)
        return True

    return False


def _calculate_pricing_and_update_notification(
    price_in_millicents_usd: float,
    notification: Notification,
    notification_status: str,
    number_of_message_parts: int,
    incoming_status_reason: str = None,
):
    """
    Calculate pricing, and update the notification.
    """

    current_app.logger.debug('Calculate pricing and update notification %s', notification.id)

    # Delivered messages should not have an associated reason.
    status_reason = (
        None
        if (notification_status == NOTIFICATION_DELIVERED)
        else incoming_status_reason or notification.status_reason
    )

    if price_in_millicents_usd > 0.0:
        dao_update_notification_by_id(
            notification_id=notification.id,
            status=notification_status,
            status_reason=status_reason,
            segments_count=number_of_message_parts,
            cost_in_millicents=price_in_millicents_usd,
        )
    else:
        update_notification_delivery_status(
            notification_id=notification.id, new_status=notification_status, new_status_reason=status_reason
        )


def _get_notification_platform_status(
    self,
    provider: any,
    body: str,
    sqs_message: dict,
) -> dict:
    """Performs a translation on the body"""

    current_app.logger.info('Get Notification Platform Status')
    notification_platform_status = None
    try:
        notification_platform_status: SmsStatusRecord = provider.translate_delivery_status(body)
    except (ValueError, KeyError) as e:
        current_app.logger.error('The event stream body could not be translated.')
        current_app.logger.exception(e)
        current_app.logger.debug(sqs_message)
        raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...')

    current_app.logger.info('retrieved delivery status: %s', notification_platform_status)

    # notification_platform_status cannot be None
    if notification_platform_status is None:
        current_app.logger.error('Notification Platform Status cannot be None')
        current_app.logger.debug(body)
        raise AutoRetryException('Found no notification_platform_status, autoretrying...')

    return notification_platform_status


def _get_include_payload_status(
    self,
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

    except (AttributeError, TypeError) as e:
        current_app.logger.error('Could not determine include_payload property for ServiceCallback.')
        current_app.logger.exception(e)
        current_app.logger.debug(notification)
        raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...')

    return include_payload_status


def _get_sqs_message(event: CeleryEvent) -> dict:
    """Gets the sms message from the CeleryEvent"""
    sqs_message = None
    current_app.logger.info('Get SQS message')
    sqs_message = event.get('message')
    if sqs_message is None:
        # Logic was previously setup this way. Not sure why we're retrying on type/key errors
        current_app.logger.warning('Unable to parse event format for event: %s', event)
        raise AutoRetryException('Unable to find "message" in event, autoretrying...')
    return sqs_message


def _get_provider_info(sqs_message: dict) -> Tuple[str, any]:
    """Gets the provider_name and provider object"""
    current_app.logger.info('Get provider Information')
    provider_name = sqs_message.get('provider')
    provider = clients.get_sms_client(provider_name)

    # provider cannot None
    if provider is None:
        current_app.logger.warning('Unable to find provider given the following message: %s', sqs_message)
        raise AutoRetryException('Found no provider, autoretrying...')

    return provider_name, provider
