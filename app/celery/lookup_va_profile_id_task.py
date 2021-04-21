from app.config import QueueNames
from app.exceptions import NotificationTechnicalFailureException
from app.models import RecipientIdentifier, NOTIFICATION_TECHNICAL_FAILURE, \
    NOTIFICATION_PERMANENT_FAILURE
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from app import notify_celery
from app.dao import notifications_dao
from app import mpi_client
from app.va.identifier import IdentifierType
from app.va.mpi import MpiRetryableException, BeneficiaryDeceasedException, \
    IdentifierNotFound, MultipleActiveVaProfileIdsException


@notify_celery.task(bind=True, name="lookup-va-profile-id-tasks", max_retries=48, default_retry_delay=300)
@statsd(namespace="tasks")
def lookup_va_profile_id(self, notification_id):
    current_app.logger.info(f"Retrieving VA Profile ID from MPI for notification {notification_id}")
    notification = notifications_dao.get_notification_by_id(notification_id)

    try:
        va_profile_id = mpi_client.get_va_profile_id(notification)
        notification.recipient_identifiers.set(
            RecipientIdentifier(
                notification_id=notification.id,
                id_type=IdentifierType.VA_PROFILE_ID.value,
                id_value=va_profile_id
            ))
        notifications_dao.dao_update_notification(notification)
        current_app.logger.info(
            f"Successfully updated notification {notification_id} with VA PROFILE ID {va_profile_id}"
        )

    except MpiRetryableException as e:
        current_app.logger.warning(f"Received {str(e)} for notification {notification_id}.")
        try:
            self.retry(queue=QueueNames.RETRY)
        except self.MaxRetriesExceededError:
            message = "RETRY FAILED: Max retries reached. " \
                      f"The task lookup_va_profile_id failed for notification {notification_id}. " \
                      "Notification has been updated to technical-failure"

            notifications_dao.update_notification_status_by_id(
                notification_id, NOTIFICATION_TECHNICAL_FAILURE, status_reason=e.failure_reason
            )
            raise NotificationTechnicalFailureException(message) from e

    except (BeneficiaryDeceasedException, IdentifierNotFound, MultipleActiveVaProfileIdsException) as e:
        message = f"{e.__class__.__name__} - {str(e)}: " \
                  f"Can't proceed after querying MPI for VA Profile ID for {notification_id}. " \
                  "Stopping execution of following tasks. Notification has been updated to permanent-failure."
        current_app.logger.warning(message)
        self.request.chain = None
        notifications_dao.update_notification_status_by_id(
            notification_id, NOTIFICATION_PERMANENT_FAILURE, status_reason=e.failure_reason
        )

    except Exception as e:
        message = f"Failed to retrieve VA Profile ID from MPI for notification: {notification_id} " \
                  "Notification has been updated to technical-failure"
        current_app.logger.exception(message)

        status_reason = e.failure_reason if hasattr(e, 'failure_reason') else 'Unknown error from MPI'
        notifications_dao.update_notification_status_by_id(
            notification_id, NOTIFICATION_TECHNICAL_FAILURE, status_reason=status_reason
        )
        raise NotificationTechnicalFailureException(message) from e
