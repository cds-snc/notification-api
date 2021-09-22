from app.va.va_profile.exceptions import VAProfileIdNotFoundException
from flask import current_app
from notifications_utils.statsd_decorators import statsd

from app import notify_celery, va_profile_client
from app.config import QueueNames
from app.dao.communication_item_dao import get_communication_item
from app.dao.notifications_dao import get_notification_by_id, update_notification_status_by_id
from app.exceptions import NotificationTechnicalFailureException
from app.models import RecipientIdentifier, NOTIFICATION_PREFERENCES_DECLINED, NOTIFICATION_TECHNICAL_FAILURE
from app.va.va_profile import VAProfileRetryableException
from app.va.va_profile.va_profile_client import CommunicationItemNotFoundException
from app.va.identifier import IdentifierType


@notify_celery.task(
    bind=True, name="lookup-recipient-communication-permissions", max_retries=5, default_retry_delay=300
)
@statsd(namespace="tasks")
def lookup_recipient_communication_permissions(
        self, notification_id: str
) -> None:
    current_app.logger.info(f"Looking up communication preferences for notification_id:{notification_id}")

    notification = get_notification_by_id(notification_id)

    try:
        notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value]
    except (KeyError) as e:
        current_app.logger.info(f'{VAProfileIdNotFoundException.failure_reason} on notification '
                                f'{notification_id}')
        raise VAProfileIdNotFoundException from e

    va_profile_recipient_identifier = notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value]

    va_profile_id = va_profile_recipient_identifier.id_value
    communication_item_id = notification.template.communication_item_id
    notification_type = notification.notification_type

    if not recipient_has_given_permission(
            self,
            IdentifierType.VA_PROFILE_ID.value,
            va_profile_id,
            notification_id,
            notification_type,
            communication_item_id
    ):
        update_notification_status_by_id(notification_id, NOTIFICATION_PREFERENCES_DECLINED)
        current_app.logger.info(f"Recipient for notification {notification_id}"
                                f"has declined permission to receive notifications")
        self.request.chain = None


def recipient_has_given_permission(
        task, id_type: str,
        id_value: str,
        notification_id: str,
        notification_type: str,
        communication_item_id: str
) -> bool:
    identifier = RecipientIdentifier(id_type=id_type, id_value=id_value)

    communication_item = get_communication_item(communication_item_id)

    try:
        is_allowed = va_profile_client.get_is_communication_allowed(
            identifier, communication_item.va_profile_item_id, notification_id, notification_type
        )
        current_app.logger.info(f'Value of permission for item {communication_item.va_profile_item_id} for recipient '
                                f'{id_value} for notification {notification_id}: {is_allowed}')
        return is_allowed
    except VAProfileRetryableException as e:
        current_app.logger.exception(e)
        try:
            task.retry(queue=QueueNames.RETRY)
        except task.MaxRetriesExceededError:
            message = (
                'RETRY FAILED: Max retries reached. '
                f'The task lookup_recipient_communication_permissions failed for notification {notification_id}. '
                'Notification has been updated to technical-failure'
            )

            update_notification_status_by_id(
                notification_id, NOTIFICATION_TECHNICAL_FAILURE, status_reason=e.failure_reason
            )
            raise NotificationTechnicalFailureException(message) from e
    except CommunicationItemNotFoundException:
        current_app.logger.info(f'Communication item for recipient {id_value} not found on notification '
                                f'{notification_id}')
        return True
