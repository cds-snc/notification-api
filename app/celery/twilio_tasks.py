from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import select

from app import db, notify_celery, twilio_sms_client
from app.celery.exceptions import NonRetryableException
from app.constants import NOTIFICATION_STATUS_TYPES_COMPLETED
from app.models import Notification


def _get_notifications() -> list:
    """Returns a list of notifications not in final state."""

    current_app.logger.info('Getting notifications to update status')
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    stmt = (
        select(Notification)
        .where(Notification.notification_type == 'sms')
        .where(Notification.sent_by == 'twilio')
        .where(~Notification.status.in_(NOTIFICATION_STATUS_TYPES_COMPLETED))
        .where(Notification.created_at < one_hour_ago)
        .order_by(Notification.created_at)
        .limit(current_app.config['TWILIO_STATUS_PAGE_SIZE'])
    )
    return db.session.scalars(stmt).all()


@notify_celery.task(name='update-twilio-status')
def update_twilio_status():
    """Update the status of notifications sent via Twilio. This task is scheduled to run every 5 minutes. It fetches
    notifications that are not in a final state, limited to the config setting TWILIO_STATUS_PAGE_SIZE, and updates
    their status using the app's Twilio client.
    """
    notifications = _get_notifications()
    current_app.logger.info('Found %s notifications to update', len(notifications))

    for notification in notifications:
        current_app.logger.info('Updating notification %s with status %s', notification.id, notification.status)
        try:
            twilio_sms_client.update_notification_status_override(notification.reference)
        except NonRetryableException as e:
            current_app.logger.error(
                'Failed to update notification %s: %s due to rate limit, aborting.', str(notification.id), str(e)
            )
            break
        else:
            current_app.logger.info('Notification %s updated', notification.id)

    current_app.logger.info('Finished updating notifications')
