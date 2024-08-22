from typing import Optional
from sqlalchemy.orm.exc import NoResultFound
from flask import current_app
from app import notify_celery, va_profile_client
from app.celery.common import can_retry, handle_max_retries_exceeded
from app.celery.exceptions import AutoRetryException
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.feature_flags import FeatureFlag, is_feature_enabled
from app.va.identifier import IdentifierType
from app.va.va_profile import VAProfileRetryableException, VAProfileNonRetryableException, NoContactInfoException
from app.dao.communication_item_dao import get_communication_item
from app.dao.notifications_dao import get_notification_by_id, dao_update_notification, update_notification_status_by_id
from app.models import NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_PREFERENCES_DECLINED, EMAIL_TYPE, SMS_TYPE
from app.exceptions import NotificationTechnicalFailureException, NotificationPermanentFailureException
from app.va.va_profile.exceptions import (VAProfileIDNotFoundException, CommunicationItemNotFoundException,
                                          CommunicationPermissionDenied)
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
        if EMAIL_TYPE == notification.notification_type:
            if (is_feature_enabled(FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP)
                    and communication_item_id_for_permission_check is not None):
                recipient = va_profile_client.get_email_with_permission(
                    recipient_identifier, communication_item_id_for_permission_check)
            else:
                recipient = va_profile_client.get_email(recipient_identifier)
        elif SMS_TYPE == notification.notification_type:
            if (is_feature_enabled(FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP)
                    and communication_item_id_for_permission_check is not None):
                recipient = va_profile_client.get_telephone_with_permission(
                    recipient_identifier, communication_item_id_for_permission_check)
            else:
                recipient = va_profile_client.get_telephone(recipient_identifier)
        else:
            raise NotImplementedError(
                f'The task lookup_contact_info failed for notification {notification_id}. '
                f'{notification.notification_type} is not supported'
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
    except CommunicationItemNotFoundException:
        current_app.logger.info(
            'Communication item for recipient %s not found on notification %s', va_profile_id, notification_id
        )
        reason = 'No recipient opt-in found for explicit preference'
        handle_lack_of_permission(notification_id, notification, reason)
    except CommunicationPermissionDenied:
        current_app.logger.info(
            'Permission denied for recipient %s for notification %s', va_profile_id, notification_id,
        )
        reason = 'Contact preferences set to false'
        handle_lack_of_permission(notification_id, notification, reason)

    notification.to = recipient
    dao_update_notification(notification)


def get_communication_item_id_for_permission_check(notification_id: str, communication_item_id: str) -> Optional[str]:
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

    update_notification_status_by_id(
        notification_id, NOTIFICATION_PREFERENCES_DECLINED, status_reason=reason
    )
    message = f'The recipient for notification {notification_id} has declined permission to receive notifications.'
    current_app.logger.info(message)
    check_and_queue_callback_task(notification)
    raise NotificationPermanentFailureException(message)
