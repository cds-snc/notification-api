from app.models import RecipientIdentifier, VA_PROFILE_ID
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from app import notify_celery
from app.dao import notifications_dao
from app import mpi_client


@notify_celery.task(name="lookup-va-profile-id-tasks")
@statsd(namespace="tasks")
def lookup_va_profile_id(notification_id):
    notification = notifications_dao.get_notification_by_id(notification_id)
    va_profile_id = mpi_client.get_va_profile_id(notification)
    notification.recipient_identifiers.set(
        RecipientIdentifier(
            notification_id=notification.id,
            id_type=VA_PROFILE_ID,
            id_value=va_profile_id
        ))
    notifications_dao.dao_update_notification(notification)
