from app import notify_celery, va_profile_client
from app.celery.common import can_retry, handle_max_retries_exceeded
from app.celery.exceptions import AutoRetryException
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.dao.communication_item_dao import get_communication_item
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
from app.va.va_profile.exceptions import (
    VAProfileIDNotFoundException,
    CommunicationItemNotFoundException,
)
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from requests import Timeout
from sqlalchemy.orm.exc import NoResultFound
from typing import Optional


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
    communication_item_id_for_permission_check: str | None,
) -> VAProfileResult:
    """
    Retrieve the result of looking up contact info from VA Profile.

    Args:
        notification_type (str): The type of contact info requested.
        notification_id (str): The notification ID associated with this request.
        recipient_identifier (RecipientIdentifier): The VA profile ID to retrieve the profile for.
        communication_item_id_for_permission_check (str): The communication_item_id to use for checking permissions.

    Returns:
        VAProfileResult: The contact info result from VA Profile.
    """
    if notification_type == EMAIL_TYPE:
        return get_email_result(notification_id, recipient_identifier, communication_item_id_for_permission_check)
    elif notification_type == SMS_TYPE:
        return get_sms_result(notification_id, recipient_identifier, communication_item_id_for_permission_check)
    else:
        raise NotImplementedError(
            f'The task lookup_contact_info failed for notification {notification_id}. '
            f'{notification_type} is not supported'
        )


def get_email_result(
    notification_id: str,
    recipient_identifier: RecipientIdentifier,
    communication_item_id_for_permission_check: str | None,
) -> VAProfileResult:
    """
    Retrieve the result of looking up email from VA Profile.

    Args:
        notification_id (str): The notification ID associated with this request.
        recipient_identifier (RecipientIdentifier): The VA profile ID to retrieve the profile for.
        communication_item_id_for_permission_check (str): The communication_item_id to use for checking permissions.

    Returns:
        VAProfileResult: The email result from VA Profile.
    """
    if communication_item_id_for_permission_check is None:
        current_app.logger.info('Bypassing permission check for %s', notification_id)
        return va_profile_client.get_email_with_permission(recipient_identifier, True)
    else:
        return va_profile_client.get_email_with_permission(recipient_identifier)


def get_sms_result(
    notification_id: str,
    recipient_identifier: RecipientIdentifier,
    communication_item_id_for_permission_check: str | None,
) -> VAProfileResult:
    """
    Retrieve the result of looking up SMS info from VA Profile.

    Args:
        notification_id (str): The notification ID associated with this request.
        recipient_identifier (RecipientIdentifier): The VA profile ID to retrieve the profile for.
        communication_item_id_for_permission_check (str): The communication_item_id to use for checking permissions.

    Returns:
        VAProfileResult: The SMS result from VA Profile.
    """
    if communication_item_id_for_permission_check is None:
        current_app.logger.info('Bypassing permission check for %s', notification_id)
        return va_profile_client.get_telephone_with_permission(recipient_identifier, True)
    else:
        return va_profile_client.get_telephone_with_permission(recipient_identifier)


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
    recipient_identifier = notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value]
    va_profile_id = recipient_identifier.id_value

    communication_item_id_for_permission_check = None
    if is_feature_enabled(FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP):
        communication_item_id = notification.template.communication_item_id
        communication_item_id_for_permission_check = get_communication_item_id_for_permission_check(
            notification_id,
            communication_item_id,
        )

    try:
        if is_feature_enabled(FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP):
            result = get_profile_result(
                notification.notification_type,
                notification_id,
                recipient_identifier,
                communication_item_id_for_permission_check,
            )
            recipient = result.recipient
            communication_allowed = result.communication_allowed
            permission_message = result.permission_message
        else:
            recipient = get_recipient(
                notification.notification_type,
                notification_id,
                recipient_identifier,
            )
    except (Timeout, VAProfileRetryableException) as e:
        if can_retry(self.request.retries, self.max_retries, notification_id):
            current_app.logger.warning('Unable to get contact info for notification id: %s, retrying', notification_id)
            raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...', e, e.args)
        else:
            msg = handle_max_retries_exceeded(notification_id, 'lookup_contact_info')
            check_and_queue_callback_task(notification)
            raise NotificationTechnicalFailureException(msg)
    except NoContactInfoException as e:
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
    except (VAProfileIDNotFoundException, VAProfileNonRetryableException) as e:
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

    notification.to = recipient
    dao_update_notification(notification)

    if is_feature_enabled(FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP):
        if not communication_allowed:
            current_app.logger.info(
                'Permission denied for recipient %s for notification %s',
                va_profile_id,
                notification_id,
            )
            if not permission_message is None:
                reason = permission_message
            else:
                reason = 'Contact preferences set to false'
            handle_lack_of_permission(notification_id, notification, reason)


def get_communication_item_id_for_permission_check(
    notification_id: str,
    communication_item_id: str,
) -> Optional[str]:
    """
    Return None if we should send regardless of communication permissions.
    Otherwise, return the communication_item_id for the permissions check.
    """

    default_send_flag = True
    communication_item = None

    try:
        communication_item = get_communication_item(communication_item_id)
    except NoResultFound:
        current_app.logger.info('No communication item found for notification %s', notification_id)

    if communication_item is None:
        # Calling va_profile without a communication item won't return anything.
        # Perform default behavior of sending the notification.
        return None

    # get default send flag when available
    default_send_flag = communication_item.default_send_indicator
    if default_send_flag:
        # Always send
        return None

    return communication_item.va_profile_item_id


def handle_lack_of_permission(notification_id: str, notification, reason: str):
    # The recipient doesn't grant permission.  a.k.a. preferences-declined

    update_notification_status_by_id(notification_id, NOTIFICATION_PREFERENCES_DECLINED, status_reason=reason)
    message = f'The recipient for notification {notification_id} has declined permission to receive notifications.'
    current_app.logger.info(message)
    check_and_queue_callback_task(notification)
    raise NotificationPermanentFailureException(message)
