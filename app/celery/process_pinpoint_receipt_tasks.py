import datetime
import json

import iso8601
from celery.exceptions import Retry
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound

from app import notify_celery, statsd_client
from app.config import QueueNames
from app.dao import notifications_dao
from app.models import (
    NOTIFICATION_SENT, NOTIFICATION_DELIVERED, NOTIFICATION_TECHNICAL_FAILURE, NOTIFICATION_SENDING,
    NOTIFICATION_PENDING
)
from app.notifications.notifications_ses_callback import _check_and_queue_callback_task

_type_status_mapping = {
    '_SMS.BUFFERED': {
        'notification_status': NOTIFICATION_SENT
    },
    '_SMS.SUCCESS': {
        'notification_status': NOTIFICATION_DELIVERED
    },
    '_SMS.FAILURE': {
        'notification_status': NOTIFICATION_TECHNICAL_FAILURE
    },
    '_SMS.OPTOUT': {
        'notification_status': NOTIFICATION_DELIVERED
    }
}


def _map_event_type_record_status_to_notification_status(event_type):

    return _type_status_mapping[event_type]['notification_status']


@notify_celery.task(bind=True, name="process-ses-result", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def process_pinpoint_results(self, response):
    try:
        pinpoint_message = json.loads(response['Message'])
        event_type = pinpoint_message.get('event_type')
        notification_status = _map_event_type_record_status_to_notification_status(event_type)

        reference = pinpoint_message['attributes']['sender_request_id']

        try:
            notification = notifications_dao.dao_get_notification_by_reference(reference)
        except NoResultFound:
            message_time = iso8601.parse_date(pinpoint_message['event_timestamp']).replace(tzinfo=None)
            if datetime.datetime.utcnow() - message_time < datetime.timedelta(minutes=5):
                self.retry(queue=QueueNames.RETRY)
            else:
                current_app.logger.warning(
                    "notification not found for reference: {} (update to {})".format(reference, notification_status)
                )
            return

        if notification.status not in {NOTIFICATION_SENDING, NOTIFICATION_PENDING}:
            notifications_dao._duplicate_update_warning(notification, notification_status)
            return

        notifications_dao.update_notification_status_by_id(notification.id, notification_status)

        current_app.logger.info(
            f"PinPoint callback return status of {notification_status} for notification: {notification.id}"
        )

        statsd_client.incr(f"callback.pinpoint.{notification_status}")

        if notification.sent_at:
            statsd_client.timing_with_dates(
                'callback.pinpoint.elapsed-time', datetime.datetime.utcnow(), notification.sent_at)

        _check_and_queue_callback_task(notification)

        return True

    except Retry:
        raise

    except Exception as e:
        current_app.logger.exception(f"Error processing PinPoint results: {type(e)}")
        self.retry(queue=QueueNames.RETRY)
