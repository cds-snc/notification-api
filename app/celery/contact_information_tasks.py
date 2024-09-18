from flask import current_app
from app import notify_celery, va_profile_client
from app.celery.common import can_retry, handle_max_retries_exceeded
from app.celery.exceptions import AutoRetryException
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.va.identifier import IdentifierType
from app.va.va_profile import VAProfileRetryableException, VAProfileNonRetryableException, NoContactInfoException
from app.dao.notifications_dao import get_notification_by_id, dao_update_notification, update_notification_status_by_id
from app.models import NOTIFICATION_PERMANENT_FAILURE, EMAIL_TYPE, SMS_TYPE
from app.exceptions import NotificationTechnicalFailureException, NotificationPermanentFailureException
from app.va.va_profile.exceptions import VAProfileIDNotFoundException
from notifications_utils.statsd_decorators import statsd
from requests import Timeout


@notify_celery.task(
    bind=True,
    name='lookup-contact-info-tasks',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=2886,
    retry_backoff=True,
    retry_backoff_max=60,
)
@statsd(namespace='tasks')
def lookup_contact_info(
    self,
    notification_id,
):
    current_app.logger.info('Looking up contact information for notification_id: %s.', notification_id)

    notification = get_notification_by_id(notification_id)
    recipient_identifier = notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value]

    try:
        if EMAIL_TYPE == notification.notification_type:
            recipient = va_profile_client.get_email(recipient_identifier)
        elif SMS_TYPE == notification.notification_type:
            recipient = va_profile_client.get_telephone(recipient_identifier)
        else:
            raise NotImplementedError(
                f'The task lookup_contact_info failed for notification {notification_id}. '
                f'{notification.notification_type} is not supported'
            )
    except (Timeout, VAProfileRetryableException) as e:
        if can_retry(self.request.retries, self.max_retries, notification_id):
            current_app.logger.warning('Unable to get contact info for notification id: %s, retrying', notification_id)
            raise AutoRetryException(f'Found {type(e).__name__}, autoretrying...', e, e.args)
        else:
            msg = handle_max_retries_exceeded(notification_id, 'lookup_contact_info')
            check_and_queue_callback_task(notification)
            raise NotificationTechnicalFailureException(msg)
    except NoContactInfoException as e:
        message = (
            f"Can't proceed after querying VA Profile for contact information for {notification_id}. "
            'Stopping execution of following tasks. Notification has been updated to permanent-failure.'
        )
        current_app.logger.warning('%s - %s:  %s', e.__class__.__name__, str(e), message)

        update_notification_status_by_id(
            notification_id, NOTIFICATION_PERMANENT_FAILURE, status_reason=e.failure_reason
        )
        check_and_queue_callback_task(notification)
        raise NotificationPermanentFailureException(message) from e
    except (VAProfileIDNotFoundException, VAProfileNonRetryableException) as e:
        current_app.logger.exception(e)
        message = (
            f'The task lookup_contact_info failed for notification {notification_id}. '
            'Notification has been updated to permanent-failure'
        )
        update_notification_status_by_id(
            notification_id, NOTIFICATION_PERMANENT_FAILURE, status_reason=e.failure_reason
        )
        check_and_queue_callback_task(notification)
        raise NotificationPermanentFailureException(message) from e

    notification.to = recipient
    dao_update_notification(notification)
