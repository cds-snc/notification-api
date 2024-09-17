from app import notify_celery, va_profile_client
from app.celery.common import can_retry, handle_max_retries_exceeded
from app.celery.exceptions import AutoRetryException
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.dao.notifications_dao import get_notification_by_id, dao_update_notification, update_notification_status_by_id
from app.exceptions import NotificationTechnicalFailureException, NotificationPermanentFailureException
from app.feature_flags import FeatureFlag, is_feature_enabled
from app.models import (
    NOTIFICATION_PERMANENT_FAILURE,
    EMAIL_TYPE,
    SMS_TYPE,
)
from app.va.identifier import IdentifierType
from app.va.va_profile import (
    VAProfileRetryableException,
    VAProfileNonRetryableException,
    NoContactInfoException,
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
    recipient_identifier = notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value]

    if is_feature_enabled(FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP):
        handle_combined_contact_info_and_permissions_lookup(self, notification, recipient_identifier)
    else:
        try:
            if notification.notification_type == EMAIL_TYPE:
                recipient = va_profile_client.get_email(recipient_identifier)
            elif notification.notification_type == SMS_TYPE:
                recipient = va_profile_client.get_telephone(recipient_identifier)
            else:
                raise NotImplementedError(
                    f'The task lookup_contact_info failed for notification {notification_id}. '
                    f'{notification.notification_type} is not supported'
                )
        except Exception as e:
            handle_lookup_contact_info_exception(self, notification, recipient_identifier, e)

        notification.to = recipient
        dao_update_notification(notification)


def handle_combined_contact_info_and_permissions_lookup(self, notification, recipient_identifier):
    try:
        if notification.notification_type == EMAIL_TYPE:
            result = va_profile_client.get_email_with_permission(recipient_identifier, notification.default_send)
        elif notification.notification_type == SMS_TYPE:
            result = va_profile_client.get_telephone_with_permission(recipient_identifier, notification.default_send)
        else:
            raise NotImplementedError(
                f'The task lookup_contact_info failed for notification {notification.id}. '
                f'{notification.notification_type} is not supported'
            )
    except Exception as e:
        handle_lookup_contact_info_exception(self, notification, recipient_identifier, e)

    notification.to = result.recipient
    dao_update_notification(notification)

    if not result.communication_allowed:
        current_app.logger.info(
            'Permission denied for recipient %s for notification %s',
            recipient_identifier.id_value,
            notification.id,
        )
        check_and_queue_callback_task(notification)
        message = result.permission_message if result.permission_message else 'Contact preferences set to False'
        raise NotificationPermanentFailureException(message)


def handle_lookup_contact_info_exception(self, notification, recipient_identifier, e):
    if isinstance(e, (Timeout, VAProfileRetryableException)):
        if can_retry(self.request.retries, self.max_retries, notification.id):
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

        return None if notification.template.default_send else 'No recipient opt-in found for explicit preference'
    else:
        current_app.logger.exception('Unhandled exception for notification %s: %s', notification.id, e)
        raise e
