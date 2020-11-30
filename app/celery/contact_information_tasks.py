from flask import current_app
from notifications_utils.statsd_decorators import statsd
from app import notify_celery, va_profile_client
from app.celery import provider_tasks
from app.clients.va_profile.va_profile_client import VAProfileException
from app.config import QueueNames
from app.dao.notifications_dao import get_notification_by_id, dao_update_notification, update_notification_status_by_id
from app.models import VA_PROFILE_ID, NOTIFICATION_TECHNICAL_FAILURE


@notify_celery.task(name="lookup-contact-info-tasks")
@statsd(namespace="tasks")
def lookup_contact_info(notification_id):
    current_app.logger.info(f"Looking up contact information for notification_id:{notification_id}.")

    notification = get_notification_by_id(notification_id)

    va_profile_id = notification.recipient_identifiers[VA_PROFILE_ID].id_value

    try:
        email = va_profile_client.get_email(va_profile_id)

        notification.to = email
        dao_update_notification(notification)

        provider_tasks.deliver_email.apply_async(
            [str(notification.id)],
            queue=QueueNames.SEND_EMAIL if not notification.service.research_mode else QueueNames.RESEARCH_MODE
        )
    except VAProfileException as e:
        current_app.logger.exception(e)
        update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)


@notify_celery.task(name="lookup-va-profile-id-tasks")
@statsd(namespace="tasks")
def lookup_va_profile_id(notification_id):
    current_app.logger.info("This task will look up VA Profile ID.")
