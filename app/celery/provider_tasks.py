from flask import current_app
from notifications_utils.recipients import InvalidEmailError
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound

from app import notify_celery
from app.config import QueueNames
from app.dao import notifications_dao
from app.dao.notifications_dao import update_notification_status_by_id
from app.delivery import send_to_providers
from app.exceptions import NotificationTechnicalFailureException, MalwarePendingException
from app.models import NOTIFICATION_TECHNICAL_FAILURE


# Celery rate limits are per worker instance and not a global rate limit.
# https://docs.celeryproject.org/en/stable/userguide/tasks.html#Task.rate_limit
# This task is dispatched through the `send-throttled-sms-tasks`
# queue. This queue is consumed by 1 Celery instance
# with 1 worker, the SMS Celery pod.
@notify_celery.task(
    bind=True,
    name="deliver_throttled_sms",
    max_retries=48,
    default_retry_delay=300,
    rate_limit="1/s",
)
@statsd(namespace="tasks")
def deliver_throttled_sms(self, notification_id):
    _deliver_sms(self, notification_id)


# Celery rate limits are per worker instance and not a global rate limit.
# https://docs.celeryproject.org/en/stable/userguide/tasks.html#Task.rate_limit
# This task is dispatched through the `send-sms-tasks`
# queue. This queue is consumed by 6 Celery instances
# with 4 workers in production.
# The maximum throughput is therefore 6*4 = 24 tasks per second
# with a rate limit of 1/s
@notify_celery.task(
    bind=True,
    name="deliver_sms",
    max_retries=48,
    default_retry_delay=300,
    rate_limit="1/s",
)
@statsd(namespace="tasks")
def deliver_sms(self, notification_id):
    _deliver_sms(self, notification_id)


@notify_celery.task(bind=True, name="deliver_email", max_retries=48, default_retry_delay=300)
@statsd(namespace="tasks")
def deliver_email(self, notification_id):
    try:
        current_app.logger.info("Start sending email for notification id: {}".format(notification_id))
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            raise NoResultFound()
        send_to_providers.send_email_to_provider(notification)
    except InvalidEmailError as e:
        current_app.logger.exception(e)
        update_notification_status_by_id(notification_id, 'technical-failure')
    except MalwarePendingException:
        current_app.logger.info(
            "RETRY: Email notification {} is pending malware scans".format(notification_id))
        self.retry(queue=QueueNames.RETRY, countdown=60)
    except Exception:
        try:
            current_app.logger.exception(
                "RETRY: Email notification {} failed".format(notification_id)
            )
            self.retry(queue=QueueNames.RETRY)
        except self.MaxRetriesExceededError:
            message = "RETRY FAILED: Max retries reached. " \
                      "The task send_email_to_provider failed for notification {}. " \
                      "Notification has been updated to technical-failure".format(notification_id)
            update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
            raise NotificationTechnicalFailureException(message)


def _deliver_sms(self, notification_id):
    try:
        current_app.logger.info("Start sending SMS for notification id: {}".format(notification_id))
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            raise NoResultFound()
        send_to_providers.send_sms_to_provider(notification)
    except Exception:
        try:
            current_app.logger.exception(
                "SMS notification delivery for id: {} failed".format(notification_id)
            )
            if self.request.retries == 0:
                self.retry(queue=QueueNames.RETRY, countdown=0)
            else:
                self.retry(queue=QueueNames.RETRY)
        except self.MaxRetriesExceededError:
            message = "RETRY FAILED: Max retries reached. The task send_sms_to_provider failed for notification {}. " \
                      "Notification has been updated to technical-failure".format(notification_id)
            update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
            raise NotificationTechnicalFailureException(message)
