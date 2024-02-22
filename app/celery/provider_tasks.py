from app import notify_celery
from app.celery.common import (
    can_retry,
    handle_max_retries_exceeded,
    log_and_update_permanent_failure,
    log_and_update_technical_failure,
)
from app.celery.exceptions import NonRetryableException, AutoRetryException
from app.clients.email.aws_ses import AwsSesClientThrottlingSendRateException
from app.config import QueueNames
from app.dao import notifications_dao
from app.dao.notifications_dao import update_notification_status_by_id
from app.dao.service_sms_sender_dao import dao_get_service_sms_sender_by_service_id_and_number
from app.delivery import send_to_providers
from app.exceptions import NotificationTechnicalFailureException, MalwarePendingException, InvalidProviderException
from app.models import NOTIFICATION_TECHNICAL_FAILURE
from app.v2.errors import RateLimitError
from flask import current_app
from notifications_utils.field import NullValueForNonConditionalPlaceholderException
from notifications_utils.recipients import InvalidEmailError, InvalidPhoneError
from notifications_utils.statsd_decorators import statsd


# Including sms_sender_id is necessary in case it's passed in when being called
@notify_celery.task(
    bind=True,
    name='deliver_sms',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=2886,
    retry_backoff=True,
    retry_backoff_max=60,
)
@statsd(namespace='tasks')
def deliver_sms(
    self,
    notification_id,
    sms_sender_id=None,
):
    try:
        current_app.logger.info('Start sending SMS for notification id: %s', notification_id)
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            # Distributed computing race condition
            current_app.logger.warning('Notification not found for: %s, retrying', notification_id)
            raise AutoRetryException
        if not notification.to:
            raise RuntimeError(
                f'The "to" field was not set for notification {notification_id}.  This is a programming error.'
            )
        send_to_providers.send_sms_to_provider(notification, sms_sender_id)
        current_app.logger.info('Successfully sent sms for notification id: %s', notification_id)
    except InvalidProviderException as e:
        log_and_update_technical_failure(
            notification_id,
            'deliver_sms',
            e,
            'SMS provider configuration invalid',
        )
        raise NotificationTechnicalFailureException(str(e))
    except InvalidPhoneError as e:
        log_and_update_permanent_failure(
            notification.id,
            'deliver_sms',
            e,
            'Phone number is invalid',
        )
    except NonRetryableException as e:
        # Max retries exceeded, celery raised exception
        log_and_update_permanent_failure(
            notification.id,
            'deliver_sms',
            e,
            'ERROR: NonRetryableException - permanent failure, not retrying',
        )
    except (NullValueForNonConditionalPlaceholderException, AttributeError, RuntimeError) as e:
        log_and_update_technical_failure(notification_id, 'deliver_sms', e)
        raise NotificationTechnicalFailureException(f'Found {type(e).__name__}, NOT retrying...', e, e.args)
    except Exception as e:
        current_app.logger.exception('SMS delivery for notification id: %s failed', notification_id)
        if can_retry(self.request.retries, self.max_retries, notification_id):
            current_app.logger.warning('Unable to send sms for notification id: %s, retrying', notification_id)
            raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...', e, e.args)
        else:
            msg = handle_max_retries_exceeded(notification_id, 'deliver_sms')
            raise NotificationTechnicalFailureException(msg)


# Including sms_sender_id is necessary in case it's passed in when being called
@notify_celery.task(
    bind=True,
    name='deliver_sms_with_rate_limiting',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=2886,
    retry_backoff=2,
    retry_backoff_max=60,
)
@statsd(namespace='tasks')
def deliver_sms_with_rate_limiting(
    self,
    notification_id,
    sms_sender_id=None,
):
    from app.notifications.validators import check_sms_sender_over_rate_limit

    try:
        current_app.logger.info('Start sending SMS with rate limiting for notification id: %s', notification_id)
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            current_app.logger.warning('Notification not found for: %s, retrying', notification_id)
            raise AutoRetryException
        if not notification.to:
            raise RuntimeError(
                f'The "to" field was not set for notification {notification_id}.  This is a programming error.'
            )
        sms_sender = dao_get_service_sms_sender_by_service_id_and_number(
            notification.service_id, notification.reply_to_text
        )
        check_sms_sender_over_rate_limit(notification.service_id, sms_sender)
        send_to_providers.send_sms_to_provider(notification, sms_sender_id)
        current_app.logger.info('Successfully sent sms with rate limiting for notification id: %s', notification_id)
    except InvalidProviderException as e:
        log_and_update_technical_failure(
            notification_id,
            'deliver_sms_with_rate_limiting',
            e,
            'SMS provider configuration invalid',
        )
        raise NotificationTechnicalFailureException(str(e))
    except InvalidPhoneError as e:
        log_and_update_permanent_failure(
            notification.id,
            'deliver_sms_with_rate_limiting',
            e,
            'Phone number is invalid',
        )
    except NonRetryableException as e:
        # Max retries exceeded, celery raised exception
        log_and_update_permanent_failure(
            notification.id,
            'deliver_sms_with_rate_limiting',
            e,
            'ERROR: NonRetryableException - permanent failure, not retrying',
        )
    except RateLimitError:
        retry_time = sms_sender.rate_limit_interval / sms_sender.rate_limit
        current_app.logger.info(
            'SMS notification delivery for id: %s failed due to rate limit being exceeded. '
            'Will retry in %d seconds.',
            notification_id,
            retry_time,
        )

        self.retry(queue=QueueNames.RATE_LIMIT_RETRY, max_retries=None, countdown=retry_time)
    except (NullValueForNonConditionalPlaceholderException, AttributeError, RuntimeError) as e:
        log_and_update_technical_failure(notification_id, 'deliver_sms_with_rate_limiting', e)
        raise NotificationTechnicalFailureException(f'Found {type(e).__name__}, NOT retrying...', e, e.args)
    except Exception as e:
        current_app.logger.exception('Rate Limit SMS notification delivery for id: %s failed', notification_id)
        if can_retry(self.request.retries, self.max_retries, notification_id):
            current_app.logger.warning(
                'Unable to send sms with rate limiting for notification id: %s, retrying', notification_id
            )
            raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...', e, e.args)
        else:
            msg = handle_max_retries_exceeded(notification_id, 'deliver_sms_with_rate_limiting')
            raise NotificationTechnicalFailureException(msg)


# Including sms_sender_id is necessary in case it's passed in when being called.
@notify_celery.task(
    bind=True,
    name='deliver_email',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=2886,
    retry_backoff=True,
    retry_backoff_max=60,
)
@statsd(namespace='tasks')
def deliver_email(
    self,
    notification_id: str,
    sms_sender_id=None,
):
    try:
        current_app.logger.info('Start sending email for notification id: %s', notification_id)
        notification = notifications_dao.get_notification_by_id(notification_id)
        if not notification:
            current_app.logger.warning('Notification not found for: %s, retrying', notification_id)
            raise AutoRetryException
        if not notification.to:
            raise RuntimeError(
                f'The "to" field was not set for notification {notification_id}.  This is a programming error.'
            )
        send_to_providers.send_email_to_provider(notification)
        current_app.logger.info('Successfully sent email for notification id: %s', notification_id)
    except InvalidEmailError as e:
        current_app.logger.exception('Email notification %s failed: %s', notification_id, str(e))
        update_notification_status_by_id(
            notification_id, NOTIFICATION_TECHNICAL_FAILURE, status_reason='Email address is in invalid format'
        )
        raise NotificationTechnicalFailureException(str(e))
    except MalwarePendingException:
        current_app.logger.info(
            'RETRY number %s: Email notification %s is pending malware scans', self.request.retries, notification_id
        )
        raise AutoRetryException('Pending malware scans...')
    except InvalidProviderException as e:
        current_app.logger.exception('Invalid provider for %s: %s', notification_id, str(e))
        update_notification_status_by_id(
            notification_id, NOTIFICATION_TECHNICAL_FAILURE, status_reason='Email provider configuration invalid'
        )
        raise NotificationTechnicalFailureException(str(e))
    except (NullValueForNonConditionalPlaceholderException, AttributeError, RuntimeError) as e:
        log_and_update_technical_failure(notification_id, 'deliver_email', e)
        raise NotificationTechnicalFailureException(f'Found {type(e).__name__}, NOT retrying...', e, e.args)
    except Exception as e:
        current_app.logger.exception('Email delivery for notification id: %s failed', notification_id)
        if can_retry(self.request.retries, self.max_retries, notification_id):
            if isinstance(e, AwsSesClientThrottlingSendRateException):
                current_app.logger.warning(
                    'RETRY number %s: Email notification %s was rate limited by SES',
                    self.request.retries,
                    notification_id,
                )
            else:
                current_app.logger.warning('Unable to send email for notification id: %s, retrying', notification_id)
            raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...', e, e.args)
        else:
            msg = handle_max_retries_exceeded(notification_id, 'deliver_email')
            raise NotificationTechnicalFailureException(msg)
