from app.celery import contact_information_tasks
from app.config import QueueNames
from app.models import RecipientIdentifier, VA_PROFILE_ID, NOTIFICATION_TECHNICAL_FAILURE
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from app import notify_celery
from app.dao import notifications_dao
from app import mpi_client
from app.va.mpi.mpi import IdentifierNotFound, UnsupportedIdentifierException


@notify_celery.task(name="lookup-va-profile-id-tasks")
@statsd(namespace="tasks")
def lookup_va_profile_id(notification_id):
    notification = notifications_dao.get_notification_by_id(notification_id)

    try:
        va_profile_id = mpi_client.get_va_profile_id(notification)
        notification.recipient_identifiers.set(
            RecipientIdentifier(
                notification_id=notification.id,
                id_type=VA_PROFILE_ID,
                id_value=va_profile_id
            ))
        notifications_dao.dao_update_notification(notification)
        current_app.logger.info(f"Successfully updated notification {notification_id} with VA PROFILE ID")
        contact_information_tasks.lookup_contact_info.apply_async(
            [notification.id],
            queue=QueueNames.LOOKUP_CONTACT_INFO
        )
    except (IdentifierNotFound, UnsupportedIdentifierException, ValueError) as e:
        current_app.logger.exception(
            f"{str(e)}. Failed to retrieve VA Profile ID from MPI for notification: {notification_id}"
        )
        notifications_dao.update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
