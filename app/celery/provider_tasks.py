from uuid import UUID

from app import notify_celery
from app.celery.common import (
    can_retry,
    handle_max_retries_exceeded,
    log_and_update_permanent_failure,
    log_and_update_critical_failure,
)
from app.celery.exceptions import AutoRetryException, NonRetryableException, RetryableException
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.clients.email.aws_ses import AwsSesClientThrottlingSendRateException
from app.config import QueueNames
from app.constants import (
    EMAIL_TYPE,
    SMS_TYPE,
    STATUS_REASON_BLOCKED,
    STATUS_REASON_INVALID_NUMBER,
    STATUS_REASON_UNDELIVERABLE,
    STATUS_REASON_UNREACHABLE,
)
from app.dao import notifications_dao
from app.dao.service_sms_sender_dao import dao_get_service_sms_sender_by_service_id_and_number
from app.delivery import send_to_providers
from app.exceptions import (
    InactiveServiceException,
    InvalidProviderException,
    NotificationTechnicalFailureException,
)
from app.models import Notification
from app.v2.errors import RateLimitError

from celery import Task
from flask import current_app
from notifications_utils.field import NullValueForNonConditionalPlaceholderException
from notifications_utils.recipients import InvalidEmailError, InvalidPhoneError
from notifications_utils.statsd_decorators import statsd


# Including sms_sender_id is necessary in case it's passed in when being called
@notify_celery.task(
    bind=True,
    name='deliver_sms',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=2886,
    retry_backoff=True,
    retry_backoff_max=60,
)
@statsd(namespace='tasks')
def deliver_sms(
    task: Task,
    notification_id,
    sms_sender_id=None,
):
    current_app.logger.info('Start sending SMS for notification id: %s', notification_id)

    try:
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            # Distributed computing race condition
            current_app.logger.warning('Notification not found for: %s, retrying', notification_id)
            raise AutoRetryException
        if not notification.to:
            raise RuntimeError(
                f'The "to" field was not set for notification {notification_id}.  This is a programming error.'
            )
        send_to_providers.send_sms_to_provider(notification, sms_sender_id)
        current_app.logger.info('Successfully sent sms for notification id: %s', notification_id)

    except Exception as e:
        _handle_delivery_failure(task, notification, 'deliver_sms', e, notification_id, SMS_TYPE)


# Including sms_sender_id is necessary in case it's passed in when being called
@notify_celery.task(
    bind=True,
    name='deliver_sms_with_rate_limiting',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=2886,
    retry_backoff=2,
    retry_backoff_max=60,
)
@statsd(namespace='tasks')
def deliver_sms_with_rate_limiting(
    task: Task,
    notification_id,
    sms_sender_id=None,
):
    from app.notifications.validators import check_sms_sender_over_rate_limit

    current_app.logger.info('Start sending SMS with rate limiting for notification id: %s', notification_id)

    try:
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            current_app.logger.warning('Notification not found for: %s, retrying', notification_id)
            raise AutoRetryException
        if not notification.to:
            raise RuntimeError(
                f'The "to" field was not set for notification {notification_id}.  This is a programming error.'
            )

        # notification.reply_to_text is set for v2 send routes in
        # app/v2/notifications/post_notifications.py::post_notification via the call to get_reply_to_text, which is
        # in the same file.  The value is a phone number.  When notification POST data specifies an SMS sender, the
        # phone number should be the phone number associated with that sender.  Otherwise, the phone number should
        # be the phone number associated with the authenticated service's default SMS sender.  Ergo, the SMS sender
        # returned in the next line should be the correct SMS sender to test for a rate-limiting condition.
        sms_sender = dao_get_service_sms_sender_by_service_id_and_number(
            notification.service_id, notification.reply_to_text
        )

        check_sms_sender_over_rate_limit(notification.service_id, sms_sender)
        send_to_providers.send_sms_to_provider(notification, sms_sender_id)
        current_app.logger.info('Successfully sent sms with rate limiting for notification id: %s', notification_id)

    except RateLimitError:
        retry_time = sms_sender.rate_limit_interval / sms_sender.rate_limit
        current_app.logger.info(
            'SMS notification delivery for id: %s failed due to rate limit being exceeded. '
            'Will retry in %s seconds.',
            notification_id,
            retry_time,
        )

        task.retry(queue=QueueNames.RETRY, max_retries=None, countdown=retry_time)

    except Exception as e:
        _handle_delivery_failure(task, notification, 'deliver_sms_with_rate_limiting', e, notification_id, SMS_TYPE)


# Including sms_sender_id is necessary because the upstream code in app/notifications/process_notifications.py
# constructs a Celery task chain using the function _get_delivery_task, and the subsequent invocation always passes
# sms_sender_id.
@notify_celery.task(
    bind=True,
    name='deliver_email',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=2886,
    retry_backoff=True,
    retry_backoff_max=60,
)
@statsd(namespace='tasks')
def deliver_email(
    task: Task,
    notification_id: UUID,
    sms_sender_id: UUID = None,
):
    current_app.logger.info('Start sending email for notification id: %s', notification_id)

    try:
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            current_app.logger.warning('Notification not found for: %s, retrying', notification_id)
            raise AutoRetryException
        if not notification.to:
            raise RuntimeError(
                f'The "to" field was not set for notification {notification_id}.  This is a programming error.'
            )
        send_to_providers.send_email_to_provider(notification)
        current_app.logger.info('Successfully sent email for notification id: %s', notification_id)

    except AwsSesClientThrottlingSendRateException as e:
        current_app.logger.warning(
            'RETRY number %s: Email notification %s was rate limited by SES',
            task.request.retries,
            notification_id,
        )
        raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...', e, e.args)

    except Exception as e:
        _handle_delivery_failure(task, notification, 'deliver_email', e, notification_id, EMAIL_TYPE)


def _handle_delivery_failure(
    celery_task: Task,
    notification: Notification | None,
    method_name: str,
    e: Exception,
    notification_id: UUID,
    notification_type: str,
) -> None:
    """Handle the various exceptions that can be raised during the delivery of an email or SMS notification

    Args:
        celery_task (Task): The task that raised an exception
        notification (Notification | None): The notification that failed to send, this can be None is rare cases
        method_name (str): The name of the method that raised an exception
        e (Exception): The exception that was raised
        notification_id (UUID): The UUID of the notification that was attempted to send when the exception was raised
        notification_type (str): This will be sms or email in this case

    Raises:
        NotificationTechnicalFailureException: If the exception is a technical failure
        AutoRetryException: If the exception can be retried
    """
    if isinstance(e, (InactiveServiceException, InvalidProviderException)):
        log_and_update_critical_failure(
            notification_id,
            method_name,
            e,
            STATUS_REASON_UNDELIVERABLE,
        )
        raise NotificationTechnicalFailureException from e

    elif isinstance(e, InvalidPhoneError):
        log_and_update_permanent_failure(
            notification_id,
            method_name,
            e,
            STATUS_REASON_INVALID_NUMBER,
        )
        raise NotificationTechnicalFailureException from e

    elif isinstance(e, InvalidEmailError):
        log_and_update_permanent_failure(
            notification_id,
            method_name,
            e,
            STATUS_REASON_UNREACHABLE,
        )
        raise NotificationTechnicalFailureException from e

    elif isinstance(e, NonRetryableException):
        if 'opted out' in str(e).lower():
            status_reason = STATUS_REASON_BLOCKED
        else:
            # Calling out this includes that are too long.
            status_reason = STATUS_REASON_UNDELIVERABLE

        log_and_update_permanent_failure(
            notification_id,
            method_name,
            e,
            status_reason,
        )
        # Expected chain termination
        celery_task.request.chain = None

    elif isinstance(e, (NullValueForNonConditionalPlaceholderException, AttributeError, RuntimeError)):
        log_and_update_critical_failure(
            notification_id,
            method_name,
            e,
            STATUS_REASON_UNDELIVERABLE,
        )
        raise NotificationTechnicalFailureException(f'Found {type(e).__name__}, NOT retrying...', e, e.args)

    else:
        if not isinstance(e, RetryableException):
            # Retryable should log where it happened, if it is here without RetryableException this is unexpected
            current_app.logger.exception('%s delivery failed for notification %s', notification_type, notification_id)

        # We retry everything because it ensures missed exceptions do not prevent notifications from going out. Logs are
        # checked daily and tickets opened for narrowing the not 'RetryableException's that make it this far.
        if can_retry(celery_task.request.retries, celery_task.max_retries, notification_id):
            current_app.logger.warning(
                '%s unable to send for notification %s, retrying',
                notification_type,
                notification_id,
            )
            raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...', e, e.args)

        else:
            msg = handle_max_retries_exceeded(notification_id, method_name)
            if notification:
                check_and_queue_callback_task(notification)
            raise NotificationTechnicalFailureException(msg)
