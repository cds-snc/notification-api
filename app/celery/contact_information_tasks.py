from celery import Task
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from requests import Timeout


from app import notify_celery, va_profile_client
from app.celery.common import can_retry, handle_max_retries_exceeded
from app.celery.exceptions import AutoRetryException
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.dao.notifications_dao import (
    get_notification_by_id,
    dao_update_notification,
    update_notification_status_by_id,
)
from app.exceptions import NotificationTechnicalFailureException, NotificationPermanentFailureException
from app.models import (
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_PREFERENCES_DECLINED,
    EMAIL_TYPE,
    SMS_TYPE,
    Notification,
    RecipientIdentifier,
)
from app.va.identifier import IdentifierType
from app.va.va_profile import (
    VAProfileRetryableException,
    VAProfileNonRetryableException,
    NoContactInfoException,
    VAProfileResult,
)
from app.va.va_profile.exceptions import VAProfileIDNotFoundException, CommunicationItemNotFoundException


@notify_celery.task(
    bind=True,
    name='lookup-contact-info-tasks',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=2886,
    retry_backoff=True,
    retry_backoff_max=60,
)
@statsd(namespace='tasks')
def lookup_contact_info(
    self: Task,
    notification_id: str,
):
    """
    Celery task to look up contact information (email/phone number) and communication permissions
    for a given notification.

    Args:
        self (Task): The Celery task instance.
        notification_id (str): The ID of the notification for which to look up contact information.

    Raises:
        AutoRetryException: If a retryable exception occurs during the lookup process.
        NotificationTechnicalFailureException: If the maximum retries have been exceeded.
        NotificationPermanentFailureException: If the exception indicates a permanent failure.
        Exception: If an unhandled exception occurs.

    Returns:
        None
    """
    current_app.logger.info('Looking up contact information for notification_id: %s.', notification_id)

    notification = get_notification_by_id(notification_id)
    recipient_identifier = notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value]

    try:
        result = get_profile_result(notification, recipient_identifier)
        notification.to = result.recipient
        if not result.communication_allowed:
            handle_communication_not_allowed(notification, recipient_identifier, result.permission_message)
        # Otherwise, this communication is allowed. We will update the notification below and continue the chain.
        # else:
        # notification.to = get_recipient(
        #     notification.notification_type,
        #     notification_id,
        #     recipient_identifier,
        # )
        dao_update_notification(notification)
    except Exception as e:
        handle_lookup_contact_info_exception(self, notification, recipient_identifier, e)


def get_profile_result(
    notification: Notification,
    recipient_identifier: RecipientIdentifier,
) -> VAProfileResult:
    """
    Retrieve the result of looking up contact info from VA Profile.

    Args:
        notification (Notification): The Notification object to get contact info and permissions for.
        recipient_identifier (RecipientIdentifier): The VA profile ID to retrieve the profile for.

    Returns:
        VAProfileResult: The contact info result from VA Profile.
    """
    if notification.notification_type == EMAIL_TYPE:
        return va_profile_client.get_email_with_permission(recipient_identifier, notification)
    elif notification.notification_type == SMS_TYPE:
        return va_profile_client.get_telephone_with_permission(recipient_identifier, notification)
    else:
        raise NotImplementedError(
            f'The task lookup_contact_info failed for notification {notification.id}. '
            f'{notification.notification_type} is not supported'
        )


def handle_lookup_contact_info_exception(
    lookup_task: Task, notification: Notification, recipient_identifier: RecipientIdentifier, e: Exception
):
    """
    Handles exceptions that occur during the lookup of contact information.

    Args:
        lookup_task (Task): The task object that is performing the lookup.
        notification (Notification): The notification object associated with the lookup.
        recipient_identifier (RecipientIdentifier): The identifier of the recipient.
        e (Exception): The exception that was raised during the lookup.

    Raises:
        AutoRetryException: If the exception is retryable and the task can be retried.
        NotificationTechnicalFailureException: If the maximum retries have been exceeded.
        NotificationPermanentFailureException: If the exception indicates a permanent failure.
        Exception: If an unhandled exception occurs.

    Returns:
        str or None: A message indicating the result of the exception handling, or None if no action is needed.
    """
    if isinstance(e, (Timeout, VAProfileRetryableException)):
        if can_retry(lookup_task.request.retries, lookup_task.max_retries, notification.id):
            current_app.logger.warning('Unable to get contact info for notification id: %s, retrying', notification.id)
            raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...', e, e.args)
        else:
            msg = handle_max_retries_exceeded(notification.id, 'lookup_contact_info')
            check_and_queue_callback_task(notification)
            raise NotificationTechnicalFailureException(msg)
    elif isinstance(e, NoContactInfoException):
        message = (
            f"Can't proceed after querying VA Profile for contact information for {notification.id}. "
            'Stopping execution of following tasks. Notification has been updated to permanent-failure.'
        )
        current_app.logger.warning('%s - %s:  %s', e.__class__.__name__, str(e), message)

        update_notification_status_by_id(
            notification.id, NOTIFICATION_PERMANENT_FAILURE, status_reason=e.failure_reason
        )
        check_and_queue_callback_task(notification)
        raise NotificationPermanentFailureException(message) from e
    elif isinstance(e, (VAProfileIDNotFoundException, VAProfileNonRetryableException)):
        current_app.logger.exception(e)
        message = (
            f'The task lookup_contact_info failed for notification {notification.id}. '
            'Notification has been updated to permanent-failure'
        )
        update_notification_status_by_id(
            notification.id, NOTIFICATION_PERMANENT_FAILURE, status_reason=e.failure_reason
        )
        check_and_queue_callback_task(notification)
        raise NotificationPermanentFailureException(message) from e
    elif isinstance(e, CommunicationItemNotFoundException):
        current_app.logger.info(
            'Communication item for recipient %s not found on notification %s',
            recipient_identifier.id_value,
            notification.id,
        )
        if not notification.default_send:
            update_notification_status_by_id(
                notification_id=notification.id,
                status=NOTIFICATION_PERMANENT_FAILURE,
                status_reason='No recipient opt-in found for explicit preference',
            )
            raise e
        else:
            # Means the default_send is True and this does not require an explicit opt-in
            return None
    else:
        current_app.logger.exception(f'Unhandled exception for notification {notification.id}: {e}')
        raise e


def handle_communication_not_allowed(
    notification: Notification, recipient_identifier: RecipientIdentifier, permission_message: str | None = None
):
    """
    Handles the scenario where communication is not allowed for a given notification.

    Args:
        notification (Notification): The notification object associated with the communication.
        recipient_identifier (RecipientIdentifier): The identifier of the recipient.
        permission_message (str): The message indicating the reason for permission denial.

    Raises:
        NotificationPermanentFailureException: If the recipient has declined permission to receive notifications.
    """
    current_app.logger.info(
        'Permission denied for recipient %s for notification %s',
        recipient_identifier.id_value,
        notification.id,
    )
    reason = permission_message if permission_message is not None else 'Contact preferences set to false'
    update_notification_status_by_id(notification.id, NOTIFICATION_PREFERENCES_DECLINED, status_reason=reason)

    message = f'The recipient for notification {notification.id} has declined permission to receive notifications.'
    current_app.logger.info(message)

    check_and_queue_callback_task(notification)
    raise NotificationPermanentFailureException(message)
