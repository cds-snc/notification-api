from flask import current_app
from notifications_utils.statsd_decorators import statsd

from app import notify_celery, va_profile_client
from app.va.identifier import IdentifierType
from app.va.va_profile import VAProfileRetryableException, VAProfileNonRetryableException, NoContactInfoException
from app.config import QueueNames
from app.dao.notifications_dao import get_notification_by_id, dao_update_notification, update_notification_status_by_id
from app.models import NOTIFICATION_TECHNICAL_FAILURE, NOTIFICATION_PERMANENT_FAILURE, EMAIL_TYPE, SMS_TYPE
from app.exceptions import NotificationTechnicalFailureException


@notify_celery.task(bind=True, name="lookup-contact-info-tasks", max_retries=48, default_retry_delay=300)
@statsd(namespace="tasks")
def lookup_contact_info(self, notification_id):
    current_app.logger.info(f"Looking up contact information for notification_id:{notification_id}.")

    notification = get_notification_by_id(notification_id)

    va_profile_id = notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value].id_value

    try:
        if EMAIL_TYPE == notification.notification_type:
            recipient = va_profile_client.get_email(va_profile_id)
        elif SMS_TYPE == notification.notification_type:
            recipient = va_profile_client.get_telephone(va_profile_id)
        else:
            raise NotImplementedError(
                f"The task lookup_contact_info failed for notification {notification_id}. "
                f"{notification.notification_type} is not supported")

    except VAProfileRetryableException as e:
        current_app.logger.exception(e)
        try:
            self.retry(queue=QueueNames.RETRY)
        except self.MaxRetriesExceededError:
            message = "RETRY FAILED: Max retries reached. " \
                      f"The task lookup_contact_info failed for notification {notification_id}. " \
                      "Notification has been updated to technical-failure"
            update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
            raise NotificationTechnicalFailureException(message) from e

    except NoContactInfoException as e:
        message = f"{e.__class__.__name__} - {str(e)}: " \
                  f"Can't proceed after querying VA Profile for contact information for {notification_id}. " \
                  "Stopping execution of following tasks. Notification has been updated to permanent-failure."
        current_app.logger.warning(message)
        self.request.chain = None
        update_notification_status_by_id(notification_id, NOTIFICATION_PERMANENT_FAILURE)

    except VAProfileNonRetryableException as e:
        current_app.logger.exception(e)
        message = f"The task lookup_contact_info failed for notification {notification_id}. " \
                  "Notification has been updated to technical-failure"
        update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
        raise NotificationTechnicalFailureException(message) from e

    else:
        notification.to = recipient
        dao_update_notification(notification)
