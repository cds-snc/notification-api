from typing import Optional
from sqlalchemy.orm.exc import NoResultFound
from app.va.va_profile.exceptions import VAProfileIdNotFoundException
from flask import current_app
from notifications_utils.statsd_decorators import statsd

from app import notify_celery, va_profile_client
from app.celery.common import can_retry, handle_max_retries_exceeded
from app.celery.exceptions import AutoRetryException
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.dao.communication_item_dao import get_communication_item
from app.dao.notifications_dao import get_notification_by_id, update_notification_status_by_id
from app.exceptions import NotificationTechnicalFailureException, NotificationPermanentFailureException
from app.models import RecipientIdentifier, NOTIFICATION_PREFERENCES_DECLINED
from app.va.va_profile import VAProfileRetryableException
from app.va.va_profile.exceptions import CommunicationItemNotFoundException
from app.va.identifier import IdentifierType


@notify_celery.task(
    bind=True,
    name='lookup-recipient-communication-permissions',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=2886,
    retry_backoff=True,
    retry_backoff_max=60,
)
@statsd(namespace='tasks')
def lookup_recipient_communication_permissions(
    self,
    notification_id: str,
) -> None:
    current_app.logger.info('Looking up communication preferences for notification_id: %s', notification_id)

    notification = get_notification_by_id(notification_id)

    try:
        va_profile_recipient_identifier = notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value]
    except KeyError as e:
        current_app.logger.info('No VA Profile ID for notification %s.', notification_id)
        raise VAProfileIdNotFoundException(f'No VA Profile ID for notification {notification_id}.') from e

    va_profile_id = va_profile_recipient_identifier.id_value
    communication_item_id = notification.template.communication_item_id
    notification_type = notification.notification_type

    try:
        status_reason = recipient_has_given_permission(
            self,
            IdentifierType.VA_PROFILE_ID.value,
            va_profile_id,
            notification_id,
            notification_type,
            communication_item_id,
        )
    except NotificationTechnicalFailureException:
        check_and_queue_callback_task(notification)
        raise

    if status_reason is not None:
        # The recipient doesn't grant permission.  a.k.a. preferences-declined

        update_notification_status_by_id(
            notification_id, NOTIFICATION_PREFERENCES_DECLINED, status_reason=status_reason
        )
        message = f'The recipient for notification {notification_id} has declined permission to receive notifications.'
        current_app.logger.info(message)
        check_and_queue_callback_task(notification)
        raise NotificationPermanentFailureException(message)


def recipient_has_given_permission(
    task, id_type: str, id_value: str, notification_id: str, notification_type: str, communication_item_id: str
) -> Optional[str]:
    """
    Return None if the recipient has the permissions.  Otherwise, return a string to explain the lack of permission.
    """

    default_send_flag = True
    communication_item = None
    identifier = RecipientIdentifier(id_type=id_type, id_value=id_value)

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

    try:
        is_allowed = va_profile_client.get_is_communication_allowed(
            identifier, communication_item.va_profile_item_id, notification_id, notification_type
        )
    except VAProfileRetryableException as e:
        if can_retry(task.request.retries, task.max_retries, notification_id):
            current_app.logger.warning(
                'Unable to look up recipient communication permissions for notification: %s', notification_id
            )
            raise AutoRetryException('Found VAProfileRetryableException, autoretrying...', e, e.args)
        else:
            msg = handle_max_retries_exceeded(notification_id, 'lookup_recipient_communication_permissions')
            raise NotificationTechnicalFailureException(msg)
    except CommunicationItemNotFoundException:
        current_app.logger.info(
            'Communication item for recipient %s not found on notification %s', id_value, notification_id
        )

        # return status reason message if message should not be sent
        return None if default_send_flag else 'No recipient opt-in found for explicit preference'

    current_app.logger.info(
        'Value of permission for item %s for recipient %s for notification %s: %s',
        communication_item.va_profile_item_id,
        id_value,
        notification_id,
        is_allowed,
    )

    # return status reason message if message should not be sent
    return None if is_allowed else 'Contact preferences set to false'
