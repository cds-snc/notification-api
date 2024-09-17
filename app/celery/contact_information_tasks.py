from app import notify_celery, va_profile_client
from app.celery.common import can_retry, handle_max_retries_exceeded
from app.celery.exceptions import AutoRetryException
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.dao.notifications_dao import get_notification_by_id, dao_update_notification, update_notification_status_by_id
from app.exceptions import NotificationTechnicalFailureException, NotificationPermanentFailureException
from app.feature_flags import FeatureFlag, is_feature_enabled
from app.models import (
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_PREFERENCES_DECLINED,
    EMAIL_TYPE,
    SMS_TYPE,
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
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from requests import Timeout


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
    self,
    notification_id,
):
    current_app.logger.info('Looking up contact information for notification_id: %s.', notification_id)

    notification = get_notification_by_id(notification_id)
    current_app.logger.debug(
        f'V3 Profile notification_id: {notification.id}, template_id: {notification.template.id} communication_item_id: {notification.template.communication_item_id}'
    )

    recipient_identifier = notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value]

    should_send = True
    try:
        if is_feature_enabled(FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP):
            should_send = notification.default_send
            result = get_profile_result(
                notification.notification_type, notification_id, recipient_identifier, should_send
            )
            recipient = result.recipient
            should_send = result.communication_allowed
            permission_message = result.permission_message
        else:
            recipient = get_recipient(
                notification.notification_type,
                notification_id,
                recipient_identifier,
            )
    except Exception as e:
        handle_lookup_contact_info_exception(self, notification, notification_id, recipient_identifier, should_send, e)

    notification.to = recipient
    dao_update_notification(notification)

    if should_send:
        handle_communication_not_allowed(notification, recipient_identifier, permission_message)


def get_recipient(
    notification_type: str,
    notification_id: str,
    recipient_identifier: RecipientIdentifier,
) -> str:
    """
    Retrieve the recipient email or phone number.

    Args:
        notification_type (str): The type of recipient info requested.
        notification_id (str): The notification ID associated with this request.
        recipient_identifier (RecipientIdentifier): The VA profile ID to retrieve the profile for.

    Returns:
        str: The recipient email or phone number.
    """
    if notification_type == EMAIL_TYPE:
        return va_profile_client.get_email(recipient_identifier)
    elif notification_type == SMS_TYPE:
        return va_profile_client.get_telephone(recipient_identifier)
    else:
        raise NotImplementedError(
            f'The task lookup_contact_info failed for notification {notification_id}. '
            f'{notification_type} is not supported'
        )


def get_profile_result(
    notification_type: str,
    notification_id: str,
    recipient_identifier: RecipientIdentifier,
    default_send: bool,
) -> VAProfileResult:
    """
    Retrieve the result of looking up contact info from VA Profile.

    Args:
        notification_type (str): The type of contact info requested.
        notification_id (str): The notification ID associated with this request.
        recipient_identifier (RecipientIdentifier): The VA profile ID to retrieve the profile for.
        # communication_item_id_for_permission_check (str): The communication_item_id to use for checking permissions.

    Returns:
        VAProfileResult: The contact info result from VA Profile.
    """
    if notification_type == EMAIL_TYPE:
        return va_profile_client.get_email_with_permission(recipient_identifier, default_send)
    elif notification_type == SMS_TYPE:
        return va_profile_client.get_telephone_with_permission(recipient_identifier, default_send)
    else:
        raise NotImplementedError(
            f'The task lookup_contact_info failed for notification {notification_id}. '
            f'{notification_type} is not supported'
        )


def handle_lookup_contact_info_exception(
    lookup_task, notification, notification_id, recipient_identifier, default_send_flag, e
):
    if isinstance(e, (Timeout, VAProfileRetryableException)):
        if can_retry(lookup_task.request.retries, lookup_task.max_retries, notification_id):
            current_app.logger.warning('Unable to get contact info for notification id: %s, retrying', notification_id)
            raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...', e, e.args)
        else:
            msg = handle_max_retries_exceeded(notification_id, 'lookup_contact_info')
            check_and_queue_callback_task(notification)
            raise NotificationTechnicalFailureException(msg)
    elif isinstance(e, NoContactInfoException):
        message = (
            f"Can't proceed after querying VA Profile for contact information for {notification_id}. "
            'Stopping execution of following tasks. Notification has been updated to permanent-failure.'
        )
        current_app.logger.warning('%s - %s:  %s', e.__class__.__name__, str(e), message)

        update_notification_status_by_id(
            notification_id, NOTIFICATION_PERMANENT_FAILURE, status_reason=e.failure_reason
        )
        check_and_queue_callback_task(notification)
        raise NotificationPermanentFailureException(message) from e
    elif isinstance(e, (VAProfileIDNotFoundException, VAProfileNonRetryableException)):
        current_app.logger.exception(e)
        message = (
            f'The task lookup_contact_info failed for notification {notification_id}. '
            'Notification has been updated to permanent-failure'
        )
        update_notification_status_by_id(
            notification_id, NOTIFICATION_PERMANENT_FAILURE, status_reason=e.failure_reason
        )
        check_and_queue_callback_task(notification)
        raise NotificationPermanentFailureException(message) from e
    elif isinstance(e, CommunicationItemNotFoundException):
        current_app.logger.info(
            'Communication item for recipient %s not found on notification %s',
            recipient_identifier.id_value,
            notification_id,
        )

        return None if default_send_flag else 'No recipient opt-in found for explicit preference'
    else:
        current_app.logger.exception(f'Unhandled exception for notification {notification_id}: {e}')
        raise e


def handle_communication_not_allowed(notification, recipient_identifier, permission_message):
    if is_feature_enabled(FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP):
        current_app.logger.info(
            'Permission denied for recipient %s for notification %s',
            recipient_identifier.id_value,
            notification.id,
        )
        if permission_message is not None:
            reason = permission_message
        else:
            reason = 'Contact preferences set to false'
        update_notification_status_by_id(notification.id, NOTIFICATION_PREFERENCES_DECLINED, status_reason=reason)
        message = f'The recipient for notification {notification.id} has declined permission to receive notifications.'
        current_app.logger.info(message)
        check_and_queue_callback_task(notification)
        raise NotificationPermanentFailureException(message)
