import iso8601

from celery.exceptions import Retry
from datetime import datetime, timedelta
from flask import (
    current_app,
    json,
)
from json import JSONDecodeError

from notifications_utils.statsd_decorators import statsd

from app import notify_celery
from app.celery.common import log_notification_total_time
from app.celery.send_va_profile_notification_status_tasks import check_and_queue_va_profile_notification_status_callback
from app.celery.service_callback_tasks import publish_complaint
from app.config import QueueNames
from app.constants import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_TEMPORARY_FAILURE,
    STATUS_REASON_RETRYABLE,
    STATUS_REASON_UNREACHABLE,
)
from app.clients.email.aws_ses import get_aws_responses
from app.dao import notifications_dao
from app.notifications.notifications_ses_callback import (
    determine_notification_bounce_type,
    handle_ses_complaint,
)
from app.celery.service_callback_tasks import check_and_queue_callback_task


@notify_celery.task(bind=True, name='process-ses-result', max_retries=5, default_retry_delay=300)
@statsd(namespace='tasks')
def process_ses_results(  # noqa: C901 (too complex 19 > 10)
    self,
    response,
):
    current_app.logger.debug('Full SES result response: %s', response)

    try:
        ses_message = json.loads(response['Message'])
    except JSONDecodeError:
        current_app.logger.exception('Error decoding SES results: full response data: %s', response)
        return

    reference = ses_message.get('mail', {}).get('messageId')
    if not reference:
        current_app.logger.warning(
            'SES complaint: unable to lookup notification, messageId (reference) was None | ses_message: %s',
            ses_message,
        )
        return

    notification_type = ses_message.get('eventType')
    if notification_type is None:
        current_app.logger.warning(
            'SES response: nothing to process, eventType was None | ses_message: %s',
            ses_message,
        )
        return

    try:
        if notification_type == 'Bounce':
            # Bounces have ran their course with AWS and should be considered done. Clients can retry soft bounces.
            notification_type = determine_notification_bounce_type(notification_type, ses_message)
        elif notification_type == 'Complaint':
            try:
                notification = notifications_dao.dao_get_notification_history_by_reference(reference)
            except Exception:
                # we expect results or no results but it could be multiple results
                message_time = iso8601.parse_date(ses_message['mail']['timestamp']).replace(tzinfo=None)
                if datetime.utcnow() - message_time < timedelta(minutes=5):
                    self.retry(queue=QueueNames.RETRY)
                else:
                    current_app.logger.warning('SES complaint: notification not found | reference: %s', reference)
                return

            complaint, recipient_email = handle_ses_complaint(ses_message, notification)
            publish_complaint(complaint, notification, recipient_email)
            return

        aws_response_dict = get_aws_responses(notification_type)

        # This is the prospective, updated status.
        incoming_status = aws_response_dict['notification_status']

        try:
            notification = notifications_dao.dao_get_notification_by_reference(reference)
        except Exception:
            # we expect results or no results but it could be multiple results
            message_time = iso8601.parse_date(ses_message['mail']['timestamp']).replace(tzinfo=None)
            if datetime.utcnow() - message_time < timedelta(minutes=5):
                self.retry(queue=QueueNames.RETRY)
            else:
                current_app.logger.warning(
                    'notification not found for reference: %s (update to %s)', reference, incoming_status
                )
            return

        # Prevent regressing bounce status.  Note that this is a test of the existing status; not the new status.
        if (
            notification.status_reason
            and 'bounce' in notification.status_reason
            and notification.status
            in {
                NOTIFICATION_TEMPORARY_FAILURE,
                NOTIFICATION_PERMANENT_FAILURE,
            }
        ):
            # async from AWS means we may get a delivered status after a bounce, in rare cases
            current_app.logger.warning(
                'Notification: %s was marked as a bounce, cannot be updated to: %s',
                notification.id,
                incoming_status,
            )
            return

        # Redact personalisation when an email is in a final state. An email may go from delivered to a bounce, but
        # that will not affect the redaction, as the email will not be retried.
        if incoming_status in (NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE):
            notification.personalisation = {k: '<redacted>' for k in notification.personalisation}

        # This is a test of the new status.  Is it a bounce?
        if incoming_status in (NOTIFICATION_TEMPORARY_FAILURE, NOTIFICATION_PERMANENT_FAILURE):
            # Add the failure status reason to the notification.
            if incoming_status == NOTIFICATION_PERMANENT_FAILURE:
                failure_reason = 'Failed to deliver email due to hard bounce'
                status_reason = STATUS_REASON_UNREACHABLE
            else:
                failure_reason = 'Temporarily failed to deliver email due to soft bounce'
                status_reason = STATUS_REASON_RETRYABLE

            notification.status_reason = status_reason
            notification.status = incoming_status

            current_app.logger.warning(
                '%s - %s - in process_ses_results for notification %s',
                incoming_status,
                failure_reason,
                notification.id,
            )

            notifications_dao.dao_update_notification(notification)
            check_and_queue_callback_task(notification)
            check_and_queue_va_profile_notification_status_callback(notification)

            return
        elif incoming_status == NOTIFICATION_DELIVERED:
            # Delivered messages should never have a status reason.
            notification.status_reason = None

        if notification.status not in (NOTIFICATION_SENDING, NOTIFICATION_PENDING):
            notifications_dao.duplicate_update_warning(notification, incoming_status)
            return

        notifications_dao._update_notification_status(notification=notification, status=incoming_status)

        if not aws_response_dict['success']:
            current_app.logger.info(
                'SES delivery failed: notification id %s and reference %s has error found. Status %s',
                notification.id,
                reference,
                aws_response_dict['message'],
            )
        else:
            current_app.logger.info(
                'SES callback return status of %s for notification: %s',
                incoming_status,
                notification.id,
            )

        log_notification_total_time(
            notification.id,
            notification.created_at,
            incoming_status,
            'ses',
        )

        check_and_queue_callback_task(notification)
        check_and_queue_va_profile_notification_status_callback(notification)

        return True

    except KeyError:
        current_app.logger.exception('AWS message malformed: full response data: %s', response)

    except Retry:
        raise

    except Exception:
        current_app.logger.exception(
            'Error processing SES results: reference: %s | notification_id: %s',
            notification.reference,
            notification.id,
        )
        self.retry(queue=QueueNames.RETRY)
