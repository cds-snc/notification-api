from app import notify_celery
from app.celery.exceptions import NonRetryableException
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.clients.email.aws_ses import AwsSesClientThrottlingSendRateException
from app.config import QueueNames
from app.dao import notifications_dao
from app.dao.notifications_dao import update_notification_status_by_id
from app.dao.service_sms_sender_dao import dao_get_service_sms_sender_by_service_id_and_number
from app.delivery import send_to_providers
from app.exceptions import NotificationTechnicalFailureException, MalwarePendingException, InvalidProviderException
from app.models import NOTIFICATION_TECHNICAL_FAILURE, NOTIFICATION_PERMANENT_FAILURE
from app.v2.errors import RateLimitError
from flask import current_app
from notifications_utils.recipients import InvalidEmailError
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound


# Including sms_sender_id is necessary in case it's passed in when being called
@notify_celery.task(bind=True, name="deliver_sms", max_retries=48, default_retry_delay=300)
@statsd(namespace="tasks")
def deliver_sms(self, notification_id, sms_sender_id=None):
    try:
        current_app.logger.info(f"Start sending SMS for notification id: {notification_id}")
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            raise NoResultFound()
        send_to_providers.send_sms_to_provider(notification, sms_sender_id)
        current_app.logger.info(f"Successfully sent sms for notification id: {notification_id}")
    except InvalidProviderException as e:
        current_app.logger.exception(e)
        update_notification_status_by_id(
            notification_id,
            NOTIFICATION_TECHNICAL_FAILURE,
            status_reason="ERROR: InvalidProviderException - could not resolve provider"
        )
        raise NotificationTechnicalFailureException(str(e))
    except NonRetryableException:
        current_app.logger.exception(
            f'SMS notification delivery for id: {notification_id} failed. Not retrying.'
        )
        update_notification_status_by_id(
            notification_id,
            NOTIFICATION_PERMANENT_FAILURE,
            status_reason="ERROR: NonRetryableException - permenant failure, not retrying"
        )
        notification = notifications_dao.get_notification_by_id(notification_id)
        check_and_queue_callback_task(notification)
    except Exception:
        try:
            current_app.logger.exception(
                f"SMS notification delivery for id: {notification_id} failed"
            )
            if self.request.retries == 0:
                self.retry(queue=QueueNames.RETRY, countdown=0)
            else:
                self.retry(queue=QueueNames.RETRY)
        except self.MaxRetriesExceededError:
            message = "RETRY FAILED: Max retries reached. The task send_sms_to_provider failed for notification " \
                      f"{notification_id}. Notification has been updated to technical-failure"
            update_notification_status_by_id(
                notification_id,
                NOTIFICATION_TECHNICAL_FAILURE,
                status_reason="ERROR: MaxRetriesExceededError - 48 retries attempted but still failed to send"
            )
            raise NotificationTechnicalFailureException(message)


# Including sms_sender_id is necessary in case it's passed in when being called
@notify_celery.task(bind=True, name='deliver_sms_with_rate_limiting', max_retries=None)
@statsd(namespace='tasks')
def deliver_sms_with_rate_limiting(self, notification_id, sms_sender_id=None):
    from app.notifications.validators import check_sms_sender_over_rate_limit
    try:
        current_app.logger.info(f'Start sending SMS with rate limiting for notification id: {notification_id}')
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            raise NoResultFound()
        sms_sender = dao_get_service_sms_sender_by_service_id_and_number(notification.service_id,
                                                                         notification.reply_to_text)
        check_sms_sender_over_rate_limit(notification.service_id, sms_sender.id)
        send_to_providers.send_sms_to_provider(notification, sms_sender_id)
        current_app.logger.info(f'Successfully sent sms with rate limiting for notification id: {notification_id}')
    except InvalidProviderException as e:
        current_app.logger.exception(e)
        update_notification_status_by_id(
            notification_id,
            NOTIFICATION_TECHNICAL_FAILURE,
            status_reason="ERROR: InvalidProviderException - could not resolve provider"
        )
        raise NotificationTechnicalFailureException(str(e))
    except NonRetryableException:
        current_app.logger.exception(
            f'SMS notification delivery for id: {notification_id} failed. Not retrying.'
        )
        update_notification_status_by_id(
            notification_id,
            NOTIFICATION_PERMANENT_FAILURE,
            status_reason="ERROR: NonRetryableException - permenant failure, not retrying"
        )
        notification = notifications_dao.get_notification_by_id(notification_id)
        check_and_queue_callback_task(notification)
    except RateLimitError:
        retry_time = sms_sender.rate_limit_interval / sms_sender.rate_limit
        current_app.logger.info(
            f'SMS notification delivery for id: {notification_id} failed due to rate limit being exceeded. '
            f'Will retry in {retry_time} seconds.'
        )

        self.retry(queue=QueueNames.RATE_LIMIT_RETRY, max_retries=None, countdown=retry_time)
    except Exception:
        try:
            current_app.logger.exception(
                f'SMS notification delivery for id: {notification_id} failed'
            )
            if self.request.retries == 0:
                self.retry(queue=QueueNames.RETRY, max_retries=48, countdown=0)
            else:
                self.retry(queue=QueueNames.RETRY, max_retries=48, countdown=300)
        except self.MaxRetriesExceededError:
            message = (
                'RETRY FAILED: Max retries reached. The task send_sms_to_provider failed for '
                f'notification {notification_id}. Notification has been updated to technical-failure'
            )
            update_notification_status_by_id(
                notification_id,
                NOTIFICATION_TECHNICAL_FAILURE,
                status_reason="ERROR: MaxRetriesExceededError - 48 retries attempted but still failed to send"
            )
            raise NotificationTechnicalFailureException(message)


# Including sms_sender_id is necessary in case it's passed in when being called.
@notify_celery.task(bind=True, name="deliver_email", max_retries=48, default_retry_delay=300)
@statsd(namespace="tasks")
def deliver_email(self, notification_id: str, sms_sender_id=None):
    try:
        current_app.logger.info("Start sending email for notification id: {}".format(notification_id))
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            raise NoResultFound()
        send_to_providers.send_email_to_provider(notification)
        current_app.logger.info(f"Successfully sent email for notification id: {notification_id}")
    except InvalidEmailError as e:
        current_app.logger.exception(f"Email notification {notification_id} failed: {str(e)}")
        update_notification_status_by_id(
            notification_id,
            NOTIFICATION_TECHNICAL_FAILURE,
            status_reason=f"ERROR: InvalidEmailError - Email notification-id {notification_id} failed"
        )
        raise NotificationTechnicalFailureException(str(e))
    except MalwarePendingException:
        current_app.logger.info(
            f"RETRY number {self.request.retries}: Email notification {notification_id} is pending malware scans")
        self.retry(queue=QueueNames.RETRY, countdown=60)
    except InvalidProviderException as e:
        current_app.logger.exception(f"Invalid provider for {notification_id}: {str(e)}")
        update_notification_status_by_id(
            notification_id,
            NOTIFICATION_TECHNICAL_FAILURE,
            status_reason=f"ERROR: InvalidProviderException - Invalid provider for notification-id {notification_id}"
        )
        raise NotificationTechnicalFailureException(str(e))
    except Exception as e:
        try:
            if isinstance(e, AwsSesClientThrottlingSendRateException):
                current_app.logger.warning(
                    f"RETRY number {self.request.retries}: Email notification {notification_id} was rate limited by SES"
                )
            else:
                current_app.logger.exception(
                    f"RETRY number {self.request.retries}: Email notification {notification_id} failed"
                )
            self.retry(queue=QueueNames.RETRY)
        except self.MaxRetriesExceededError:
            message = "RETRY FAILED: Max retries reached. " \
                      "The task send_email_to_provider failed for notification {}. " \
                      "Notification has been updated to technical-failure".format(notification_id)
            update_notification_status_by_id(
                notification_id,
                NOTIFICATION_TECHNICAL_FAILURE,
                status_reason="ERROR: MaxRetriesExceededError - 48 retries attempted but still failed to send"
            )
            raise NotificationTechnicalFailureException(message)
