from typing import Optional

from flask import current_app
from notifications_utils.recipients import InvalidEmailError
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound

from app import notify_celery
from app.celery.utils import CeleryParams
from app.config import Config
from app.dao import notifications_dao
from app.dao.notifications_dao import update_notification_status_by_id
from app.delivery import send_to_providers
from app.exceptions import (
    InvalidUrlException,
    MalwareDetectedException,
    MalwareScanInProgressException,
    NotificationTechnicalFailureException,
    PinpointConflictException,
    PinpointValidationException,
)
from app.models import (
    NOTIFICATION_PINPOINT_FAILURE,
    NOTIFICATION_TECHNICAL_FAILURE,
    Notification,
)
from app.notifications.callbacks import _check_and_queue_callback_task
from celery import Task


# Celery rate limits are per worker instance and not a global rate limit.
# https://docs.celeryproject.org/en/stable/userguide/tasks.html#Task.rate_limit
# This task is dispatched through the `send-throttled-sms-tasks` queue.
# This queue is consumed by 1 Celery instance with 1 worker, the SMS Celery pod.
# The maximum throughput is therefore 1 instance * 1 worker = 1 task per rate limit.
# We the set rate_limit="30/m" on the Celery task to have 1 task per 2 seconds.
@notify_celery.task(
    bind=True,
    name="deliver_throttled_sms",
    max_retries=48,
    default_retry_delay=300,
    rate_limit="30/m",
)
@statsd(namespace="tasks")
def deliver_throttled_sms(self, notification_id):
    _deliver_sms(self, notification_id)


# Celery rate limits are per worker instance and not a global rate limit.
# https://docs.celeryproject.org/en/stable/userguide/tasks.html#Task.rate_limit
# We currently set rate_limit="1/s" on the Celery task and 4 workers per pod, and so a limit of 4 tasks per second per pod.
# The number of pods is controlled by the Kubernetes HPA and scales up and down with demand.
# Currently in production we have 3 celery-sms-send-primary pods, and up to 20 celery-sms-send-scalable pods
# This means we can send up to 92 messages per second.
@notify_celery.task(
    bind=True,
    name="deliver_sms",
    max_retries=48,
    default_retry_delay=300,
    rate_limit=Config.CELERY_DELIVER_SMS_RATE_LIMIT,
)
@statsd(namespace="tasks")
def deliver_sms(self, notification_id):
    _deliver_sms(self, notification_id)


SCAN_RETRY_BACKOFF = 10
SCAN_MAX_BACKOFF_RETRIES = 5


@notify_celery.task(bind=True, name="deliver_email", max_retries=48, default_retry_delay=300)
@statsd(namespace="tasks")
def deliver_email(self, notification_id):
    notification = None
    try:
        current_app.logger.debug("Start sending email for notification id: {}".format(notification_id))
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            raise NoResultFound()
        send_to_providers.send_email_to_provider(notification)
    except InvalidEmailError as e:
        if not notification.to.isascii():
            current_app.logger.info(f"Cannot send notification {notification_id} (has a non-ascii email address): {str(e)}")
        else:
            current_app.logger.info(f"Cannot send notification {notification_id}, got an invalid email address: {str(e)}.")
        update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
        _check_and_queue_callback_task(notification)
    except InvalidUrlException:
        current_app.logger.error(f"Cannot send notification {notification_id}, got an invalid direct file url.")
        update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
        _check_and_queue_callback_task(notification)
    except MalwareDetectedException:
        _check_and_queue_callback_task(notification)
    except MalwareScanInProgressException as me:
        if self.request.retries <= SCAN_MAX_BACKOFF_RETRIES:
            countdown = SCAN_RETRY_BACKOFF * (self.request.retries + 1)
        else:
            countdown = None
        current_app.logger.warning(
            "RETRY {}: Email notification {} is waiting on pending malware scanning".format(self.request.retries, notification_id)
        )
        _handle_error_with_email_retry(self, me, notification_id, notification, countdown)
    except Exception as e:
        _handle_error_with_email_retry(self, e, notification_id, notification)


def _deliver_sms(self, notification_id):
    try:
        current_app.logger.info("Start sending SMS for notification id: {}".format(notification_id))
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            raise NoResultFound()
        send_to_providers.send_sms_to_provider(notification)
    except InvalidUrlException:
        current_app.logger.error(f"Cannot send notification {notification_id}, got an invalid direct file url.")
        update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
        _check_and_queue_callback_task(notification)
    except (PinpointConflictException, PinpointValidationException) as e:
        # As this is due to Pinpoint errors, we are NOT retrying the notification
        # We are only warning on the error, and not logging an error
        current_app.logger.warning("SMS delivery failed for notification_id {} Pinpoint error: {}".format(notification.id, e))
        # PinpointConflictException reasons: https://botocore.amazonaws.com/v1/documentation/api/latest/reference/services/pinpoint-sms-voice-v2/client/exceptions/ConflictException.html
        # PinpointValidationException reasons: https://botocore.amazonaws.com/v1/documentation/api/latest/reference/services/pinpoint-sms-voice-v2/client/exceptions/ValidationException.html
        update_notification_status_by_id(
            notification_id, NOTIFICATION_PINPOINT_FAILURE, feedback_reason=e.original_exception.response.get("Reason", "")
        )
        _check_and_queue_callback_task(notification)
    except Exception:
        try:
            current_app.logger.exception("SMS notification delivery for id: {} failed".format(notification_id))
            self.retry(**CeleryParams.retry(None if notification is None else notification.template.process_type))
        except self.MaxRetriesExceededError:
            message = (
                "RETRY FAILED: Max retries reached. The task send_sms_to_provider failed for notification {}. "
                "Notification has been updated to technical-failure".format(notification_id)
            )
            update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
            _check_and_queue_callback_task(notification)
            raise NotificationTechnicalFailureException(message)


def _handle_error_with_email_retry(
    task: Task, e: Exception, notification_id: int, notification: Optional[Notification], countdown: Optional[None] = None
):
    try:
        if task.request.retries <= 10:
            current_app.logger.warning("RETRY {}: Email notification {} failed".format(task.request.retries, notification_id))
        else:
            current_app.logger.exception("RETRY: Email notification {} failed".format(notification_id), exc_info=e)
        # There is an edge case when a notification is not found in the database.
        if notification is None or notification.template is None:
            task.retry(**CeleryParams.retry(countdown=countdown))
        else:
            task.retry(**CeleryParams.retry(notification.template.process_type, countdown))
    except task.MaxRetriesExceededError:
        message = (
            "RETRY FAILED: Max retries reached. "
            "The task send_email_to_provider failed for notification {}. "
            "Notification has been updated to technical-failure".format(notification_id)
        )
        update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
        if notification is not None:
            _check_and_queue_callback_task(notification)
        raise NotificationTechnicalFailureException(message)
