from flask import current_app
from notifications_utils.statsd_decorators import statsd
from app import notify_celery
from app.dao import notifications_dao


@notify_celery.task(name="lookup-va-profile-id-tasks")
@statsd(namespace="tasks")
def lookup_va_profile_id(notification_id):
    notification = notifications_dao.get_notification_by_id(notification_id)
