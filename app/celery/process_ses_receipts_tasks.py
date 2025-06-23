from dataclasses import dataclass
from typing import Tuple
from celery import Task
import iso8601

from celery.exceptions import Retry
from datetime import datetime, timedelta
from enum import Enum
from flask import (
    current_app,
    json,
)
from json import JSONDecodeError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.sql.dml import Update

from notifications_utils.statsd_decorators import statsd

from app import notify_celery
from app.celery.common import log_notification_total_time
from app.celery.exceptions import NonRetryableException
from app.celery.send_va_profile_notification_status_tasks import check_and_queue_va_profile_notification_status_callback
from app.celery.service_callback_tasks import publish_complaint
from app.config import QueueNames
from app.constants import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_TEMPORARY_FAILURE,
    SES_PROVIDER,
    STATUS_REASON_RETRYABLE,
    STATUS_REASON_UNREACHABLE,
)
from app.clients.email.aws_ses import get_aws_responses
from app.dao import notifications_dao
from app.feature_flags import FeatureFlag, is_feature_enabled
from app.models import Notification, NotificationHistory
from app.notifications.notifications_ses_callback import (
    determine_notification_bounce_type,
    handle_ses_complaint,
)
from app.celery.service_callback_tasks import check_and_queue_callback_task


class SesEventType(Enum):
    BOUNCE = 'Bounce'
    COMPLAINT = 'Complaint'
    DELIVERED = 'Delivered'
    OPEN = 'Open'
    SEND = 'Send'
    RENDERING_FAILURE = 'Rendering Failure'


@dataclass
class EmailStatusRecord:
    notification: Notification | NotificationHistory
    status: str
    status_reason: str | None
    provider: str
    price_millicents: float = 0.0
    provider_updated_at: datetime | None = None


@dataclass
class SesResponse:
    """Represents all the relevant fields of an SES response."""

    event_type: SesEventType
    reference: str

    def __init__(self, eventType: str, messageId: str, *args, **kwargs):
        self.event_type = SesEventType(eventType)
        self.reference = messageId
        ...


@dataclass
class SesMail:
    timestamp: datetime
    reference: str


@notify_celery.task(bind=True, name='process-ses-result', max_retries=5, default_retry_delay=300)
@statsd(namespace='tasks')
def process_ses_results(
    task: Task,
    celery_envelope: str,
):
    current_app.logger.debug('Incoming SES response: %s', celery_envelope)

    if is_feature_enabled(FeatureFlag.EMAIL_DELIVERY_STATUS_OVERHAUL):
        # This is a general outline
        ses_response: SesResponse = _validate_response(celery_envelope)
        db_notification: Notification | NotificationHistory = _get_notification(ses_response.reference)
        current_app.logger.info(
            'SES details for notification: %s | current status: %s | event_type: %s',
            db_notification.id,
            db_notification.status,
            ses_response.event_type,
            # Add the rest
        )
        status_record, where_clause = _handle_response(ses_response, db_notification)
        notification: Notification = _update_notification_where(status_record, where_clause)

        # log status_record details
        _queue_callbacks(notification)
        log_notification_total_time(
            notification.id,
            notification.created_at,
            notification.status,
            SES_PROVIDER,
        )
    else:
        return _process_ses_results(task, celery_envelope)


def _validate_response(celery_envelope: str) -> SesResponse:
    # Tries to load the response. Validates all expected fields are available
    # Does not use get_aws_responses, uses dataclasses to map the data, with link(s) to the pages as comments
    # Maps EventType or logs and raises a non-retryable exception
    try:
        ses_event = json.loads(celery_envelope['Message'])
    except JSONDecodeError as e:
        current_app.logger.exception('Error decoding SES results: full response data: %s', celery_envelope)
        raise NonRetryableException from e

    try:
        # Ensure event_type maps here. The point of validation is so downstream code does not have to cover it
        ses_resp = SesResponse(event_type=SesEventType(ses_event.event_type))
    except ValueError as e:
        current_app.logger.exception('Unable to process SES response')
        raise NonRetryableException from e
    return ses_resp


def _get_notification(reference) -> Notification | NotificationHistory:
    try:
        notification: Notification | NotificationHistory = notifications_dao.dao_get_notification_history_by_reference(
            reference
        )
    except (MultipleResultsFound, NoResultFound, SQLAlchemyError):
        current_app.logger.exception('Unable to find SES reference: %s', reference)
        raise

    return notification


def _handle_response(
    ses_response: SesResponse, notification: Notification | NotificationHistory
) -> Tuple[EmailStatusRecord, Update]:
    # https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-examples.html#event-publishing-retrieving-sns-open
    # All should use one DAO update function with a WHERE clause similar to sms_conditions
    # The WHERE clause is made in each event handler and passes it to the update function
    # The alternative is one big clause, or duplicating the call each time
    if ses_response.event_type == SesEventType.BOUNCE:
        status_record, where_clause = _handle_bounce_event(ses_response, notification)
    elif ses_response.event_type == SesEventType.COMPLAINT:
        status_record, where_clause = _handle_complaint_event(ses_response, notification)
    elif ses_response.event_type == SesEventType.DELIVERED:
        status_record, where_clause = _handle_delivered_event(ses_response, notification)
    elif ses_response.event_type == SesEventType.OPEN:
        status_record, where_clause = _handle_open_event(ses_response, notification)
    elif ses_response.event_type == SesEventType.SEND:
        status_record, where_clause = _handle_send_event(ses_response, notification)
    elif ses_response.event_type == SesEventType.RENDERING_FAILURE:
        status_record, where_clause = _handle_rendering_failure_event(ses_response, notification)
    return status_record, where_clause


def _handle_bounce_event(ses_response: SesResponse) -> EmailStatusRecord:
    # Hard bounces always overrides any status. Soft bounces do not update final states (delivered/perm fail)
    # status_record = EmailStatusRecord(<data>)
    # status_record.where_clause = update(...).where(...).values(...)
    ...


def _handle_complaint_event(ses_response: SesResponse) -> EmailStatusRecord:
    # Complaints always override any status.
    ...


def _handle_delivered_event(ses_response: SesResponse) -> EmailStatusRecord:
    # Delivered updates for all other than perm failure.
    # Track metric for OCTO OKR 1.2
    ...


def _handle_open_event(ses_response: SesResponse) -> EmailStatusRecord:
    # Metric tracking
    ...


def _handle_send_event(ses_response: SesResponse) -> EmailStatusRecord:
    # Metric tracking, this has left AWS
    ...


def _handle_rendering_failure_event(ses_response: SesResponse) -> EmailStatusRecord:
    # Permanent failure, critical exception needs to be raised so we can raise with the business
    ...


def _update_notification_where(status_record: EmailStatusRecord, stmt: Update) -> Notification:
    # Updates the Notification table based on status_record.where_clause, returns the current notification object
    ...


def _queue_callbacks(notification):
    check_and_queue_callback_task(notification)
    check_and_queue_va_profile_notification_status_callback(notification)


def _process_ses_results(task, response):  # noqa: C901 (too complex 20 > 10)
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
                    task.retry(queue=QueueNames.RETRY)
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
                task.retry(queue=QueueNames.RETRY)
            else:
                current_app.logger.warning(
                    'notification not found for reference: %s (update to %s)', reference, incoming_status
                )
            return

        # Prevent regressing bounce status.  Note that this is a test of the existing status; not the new status.
        if notification.status_reason and (
            notification.status_reason == STATUS_REASON_UNREACHABLE
            or notification.status_reason == STATUS_REASON_RETRYABLE
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
        task.retry(queue=QueueNames.RETRY)
