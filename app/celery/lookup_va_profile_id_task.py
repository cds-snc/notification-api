from app.config import QueueNames
from app.exceptions import NotificationTechnicalFailureException
from app.models import RecipientIdentifier, VA_PROFILE_ID, NOTIFICATION_TECHNICAL_FAILURE
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from app import notify_celery
from app.dao import notifications_dao
from app import mpi_client
from app.va.mpi import MpiRetryableException, MpiNonRetryableException


@notify_celery.task(bind=True, name="lookup-va-profile-id-tasks", max_retries=48, default_retry_delay=300)
@statsd(namespace="tasks")
def lookup_va_profile_id(self, notification_id):
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
        current_app.logger.info(
            f"Successfully updated notification {notification_id} with VA PROFILE ID {va_profile_id}"
        )

    except MpiRetryableException as e:
        current_app.logger.exception(e)
        try:
            self.retry(queue=QueueNames.RETRY)
        except self.MaxRetriesExceededError:
            message = "RETRY FAILED: Max retries reached. " \
                      f"The task lookup_va_profile_id failed for notification {notification_id}. " \
                      "Notification has been updated to technical-failure"
            notifications_dao.update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
            raise NotificationTechnicalFailureException(message) from e
    except MpiNonRetryableException as e:
        message = f"{str(e)}. Failed to retrieve VA Profile ID from MPI for notification: {notification_id}"
        current_app.logger.exception(message)
        notifications_dao.update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
        raise NotificationTechnicalFailureException(message) from e
