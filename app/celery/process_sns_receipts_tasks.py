from datetime import datetime, timedelta

import iso8601
from celery.exceptions import Retry
from flask import current_app, json
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound
from app import notify_celery, statsd_client
from app.config import QueueNames
from app.dao import notifications_dao
from app.models import NOTIFICATION_SENT, NOTIFICATION_DELIVERED, NOTIFICATION_FAILED
from app.notifications.callbacks import _check_and_queue_callback_task


@notify_celery.task(
    bind=True,
    name="process-sns-result",
    max_retries=5,
    default_retry_delay=300
)
@statsd(namespace="tasks")
def process_sns_results(self, response):
    try:
        # Payload details: https://docs.aws.amazon.com/sns/latest/dg/sms_stats_cloudwatch.html
        sns_message = json.loads(response['Message'])
        reference = sns_message['notification']['messageId']
        status = sns_message['status']

        if status == 'SUCCESS':
            notification_status = NOTIFICATION_DELIVERED
        elif status == 'FAILURE':
            notification_status = NOTIFICATION_FAILED
        else:
            current_app.logger.exception(f'Unknown SNS status : {status}')

        try:
            notification = notifications_dao.dao_get_notification_by_reference(reference)
        except NoResultFound:
            message_time = iso8601.parse_date(sns_message['notification']['timestamp']).replace(tzinfo=None)
            if datetime.utcnow() - message_time < timedelta(minutes=5):
                self.retry(queue=QueueNames.RETRY)
            else:
                current_app.logger.warning(
                    f"notification not found for reference: {reference} (update to {notification_status})"
                )
            return

        if notification.sent_by != 'sns':
            current_app.logger.exception(f'SNS callback handled notification {notification.id} not sent by SNS')
            return

        if notification.status != NOTIFICATION_SENT:
            notifications_dao._duplicate_update_warning(notification, notification_status)
            return

        notifications_dao._update_notification_status(
            notification=notification,
            status=notification_status
        )

        if notification_status == NOTIFICATION_FAILED:
            current_app.logger.info((
                f"SNS delivery failed: notification id {notification.id} and reference {reference} has error found. "
                f"Provider response: {sns_message['delivery']['providerResponse']}"
            ))
        else:
            current_app.logger.info(
                f'SNS callback return status of {notification_status} for notification: {notification.id}'
            )

        statsd_client.incr(f'callback.sns.{notification_status}')

        if notification.sent_at:
            statsd_client.timing_with_dates('callback.sns.elapsed-time', datetime.utcnow(), notification.sent_at)

        _check_and_queue_callback_task(notification)

        return True

    except Retry:
        raise

    except Exception as e:
        current_app.logger.exception(f'Error processing SNS results: {str(e)}')
        self.retry(queue=QueueNames.RETRY)
