from flask import current_app
from notifications_utils.statsd_decorators import statsd
from app import notify_celery, va_profile_client
from app.dao import notifications_dao
from app.models import VA_PROFILE_ID
from app.notifications.process_notifications import send_notification_to_queue


@notify_celery.task(name="lookup-contact-info-tasks")
@statsd(namespace="tasks")
def lookup_contact_info(notification_id):
    current_app.logger.info(f"Looking up contact information for notification_id:{notification_id}.")

    notification = notifications_dao.get_notification_by_id(notification_id)

    va_profile_id = notification.recipient_identifiers[VA_PROFILE_ID].id_value

    email = va_profile_client.get_email(va_profile_id)

    notification.to = email
    notifications_dao.dao_update_notification(notification)

    send_notification_to_queue(notification, notification.service.research_mode)


@notify_celery.task(name="lookup-va-profile-id-tasks")
@statsd(namespace="tasks")
def lookup_va_profile_id(notification_id):
    current_app.logger.info("This task will look up VA Profile ID.")
