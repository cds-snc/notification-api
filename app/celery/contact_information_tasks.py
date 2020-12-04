from flask import current_app
from notifications_utils.statsd_decorators import statsd

from app import notify_celery, va_profile_client
from app.va.va_profile import VAProfileException
from app.config import QueueNames
from app.dao.notifications_dao import get_notification_by_id, dao_update_notification, update_notification_status_by_id
from app.models import VA_PROFILE_ID, NOTIFICATION_TECHNICAL_FAILURE
from app.exceptions import NotificationTechnicalFailureException


@notify_celery.task(bind=True, name="lookup-contact-info-tasks", max_retries=48, default_retry_delay=300)
@statsd(namespace="tasks")
def lookup_contact_info(self, notification_id):
    current_app.logger.info(f"Looking up contact information for notification_id:{notification_id}.")

    notification = get_notification_by_id(notification_id)

    va_profile_id = notification.recipient_identifiers[VA_PROFILE_ID].id_value

    try:
        email = va_profile_client.get_email(va_profile_id)

        notification.to = email
        dao_update_notification(notification)

    except VAProfileException as e:
        current_app.logger.exception(e)
        try:
            self.retry(queue=QueueNames.RETRY)
        except self.MaxRetriesExceededError:
            message = "RETRY FAILED: Max retries reached. " \
                      f"The task lookup_contact_info failed for notification {notification_id}. " \
                      "Notification has been updated to technical-failure"
            update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
            raise NotificationTechnicalFailureException(message)
