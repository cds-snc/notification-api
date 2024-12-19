from datetime import datetime, timedelta
from uuid import uuid4

import iso8601
from app.celery.common import log_notification_total_time
from celery.exceptions import Retry
from flask import (
    Blueprint,
    request,
    current_app,
    json,
    jsonify,
)
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound
import enum
import requests

from app import notify_celery, statsd_client
from app.celery.send_va_profile_notification_status_tasks import check_and_queue_va_profile_notification_status_callback
from app.celery.service_callback_tasks import publish_complaint
from app.config import QueueNames
from app.constants import (
    EMAIL_TYPE,
    HTTP_TIMEOUT,
    KEY_TYPE_NORMAL,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_PENDING,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    STATUS_REASON_RETRYABLE,
    STATUS_REASON_UNREACHABLE,
)
from app.clients.email.aws_ses import get_aws_responses
from app.dao import notifications_dao, services_dao, templates_dao
from json import decoder
from app.notifications import process_notifications
from app.notifications.notifications_ses_callback import (
    determine_notification_bounce_type,
    handle_ses_complaint,
    handle_smtp_complaint,
)
from app.celery.service_callback_tasks import check_and_queue_callback_task, _check_and_queue_complaint_callback_task
from app.errors import register_errors, InvalidRequest
from cachelib import SimpleCache
import validatesns

ses_callback_blueprint = Blueprint('notifications_ses_callback', __name__)
ses_smtp_callback_blueprint = Blueprint('notifications_ses_smtp_callback', __name__)

register_errors(ses_callback_blueprint)
register_errors(ses_smtp_callback_blueprint)


class SNSMessageType(enum.Enum):
    SubscriptionConfirmation = 'SubscriptionConfirmation'
    Notification = 'Notification'
    UnsubscribeConfirmation = 'UnsubscribeConfirmation'


class InvalidMessageTypeException(Exception):
    pass


def verify_message_type(message_type: str):
    try:
        SNSMessageType(message_type)
    except ValueError:
        raise InvalidMessageTypeException(f'{message_type} is not a valid message type.')


certificate_cache = SimpleCache()


def get_certificate(url):
    res = certificate_cache.get(url)
    if res is not None:
        return res
    res = requests.get(url, timeout=HTTP_TIMEOUT).content
    certificate_cache.set(url, res, timeout=60 * 60)  # 60 minutes
    return res


# 400 counts as a permanent failure so SNS will not retry.
# 500 counts as a failed delivery attempt so SNS will retry.
# See https://docs.aws.amazon.com/sns/latest/dg/DeliveryPolicies.html#DeliveryPolicies
# This should not be here, it used to be in notifications/notifications_ses_callback. It then
# got refactored into a task, which is fine, but it created a circular dependency. Will need
# to investigate why GDS extracted this into a lambda
@ses_callback_blueprint.route('/notifications/email/ses', methods=['POST'])
def sns_callback_handler():
    message_type = request.headers.get('x-amz-sns-message-type')
    try:
        verify_message_type(message_type)
    except InvalidMessageTypeException:
        raise InvalidRequest('SES-SNS callback failed: invalid message type', 400)

    try:
        message = json.loads(request.data)
    except decoder.JSONDecodeError:
        raise InvalidRequest('SES-SNS callback failed: invalid JSON given', 400)

    try:
        validatesns.validate(message, get_certificate=get_certificate)
    except validatesns.ValidationError:
        raise InvalidRequest('SES-SNS callback failed: validation failed', 400)

    if message.get('Type') == 'SubscriptionConfirmation':
        url = message.get('SubscribeURL')
        try:
            response = requests.get(url, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as e:
            current_app.logger.warning('Response: %s', response.text)
            raise e

        return jsonify(result='success', message='SES-SNS auto-confirm callback succeeded'), 200

    process_ses_results.apply_async([{'Message': message.get('Message')}], queue=QueueNames.NOTIFY)

    return jsonify(result='success', message='SES-SNS callback succeeded'), 200


@ses_smtp_callback_blueprint.route('/notifications/email/ses-smtp', methods=['POST'])
def sns_smtp_callback_handler():
    message_type = request.headers.get('x-amz-sns-message-type')
    try:
        verify_message_type(message_type)
    except InvalidMessageTypeException:
        raise InvalidRequest('SES-SNS SMTP callback failed: invalid message type', 400)

    try:
        message = json.loads(request.data)
    except decoder.JSONDecodeError:
        raise InvalidRequest('SES-SNS SMTP callback failed: invalid JSON given', 400)

    try:
        validatesns.validate(message, get_certificate=get_certificate)
    except validatesns.ValidationError:
        raise InvalidRequest('SES-SNS SMTP callback failed: validation failed', 400)

    if message.get('Type') == 'SubscriptionConfirmation':
        url = message.get('SubscribeURL')
        try:
            response = requests.get(url, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as e:
            current_app.logger.warning('Response: %s', response.text)
            raise e

        return jsonify(result='success', message='SES-SNS auto-confirm callback succeeded'), 200

    process_ses_smtp_results.apply_async([{'Message': message.get('Message')}], queue=QueueNames.NOTIFY)

    return jsonify(result='success', message='SES-SNS callback succeeded'), 200


@notify_celery.task(bind=True, name='process-ses-result', max_retries=5, default_retry_delay=300)
@statsd(namespace='tasks')
def process_ses_results(  # noqa: C901 (too complex 14 > 10)
    self,
    response,
):
    current_app.logger.debug('Full SES result response: %s', response)
    try:
        ses_message = json.loads(response['Message'])
        notification_type = ses_message.get('eventType')

        if notification_type == 'Bounce':
            # Bounces have ran their course with AWS and should be considered done. Clients can retry soft bounces.
            notification_type = determine_notification_bounce_type(notification_type, ses_message)
        elif notification_type == 'Complaint':
            complaint, notification, recipient_email = handle_ses_complaint(ses_message)
            return publish_complaint(complaint, notification, recipient_email)

        aws_response_dict = get_aws_responses(notification_type)

        # This is the prospective, updated status.
        incoming_status = aws_response_dict['notification_status']
        reference = ses_message['mail']['messageId']

        try:
            notification = notifications_dao.dao_get_notification_by_reference(reference)
        except NoResultFound:
            message_time = iso8601.parse_date(ses_message['mail']['timestamp']).replace(tzinfo=None)
            if datetime.utcnow() - message_time < timedelta(minutes=5):
                self.retry(queue=QueueNames.RETRY)
            else:
                current_app.logger.warning(
                    'notification not found for reference: %s (update to %s)', reference, incoming_status
                )
            return

        # Prevent regressing bounce status.  Note that this is a test of the existing status; not the new status.
        if notification.status_reason and notification.status in {
            NOTIFICATION_TEMPORARY_FAILURE,
            NOTIFICATION_PERMANENT_FAILURE,
        }:
            # async from AWS means we may get a delivered status after a bounce, in rare cases
            current_app.logger.warning(
                'Notification: %s was marked as a bounce, cannot be updated to: %s',
                notification.id,
                incoming_status,
            )
            return

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

    except Retry:
        raise

    except Exception as e:
        current_app.logger.exception(e)
        current_app.logger.error('Error processing SES results: %s', type(e))
        self.retry(queue=QueueNames.RETRY)


@notify_celery.task(bind=True, name='process-ses-smtp-results', max_retries=5, default_retry_delay=300)
@statsd(namespace='tasks')
def process_ses_smtp_results(
    self,
    response,
):
    try:
        ses_message = json.loads(response['Message'])

        notification_type = ses_message['eventType']
        headers = ses_message['mail']['commonHeaders']
        source = ses_message['mail']['source']
        recipients = ses_message['mail']['destination']

        if notification_type == 'Bounce':
            notification_type = determine_notification_bounce_type(notification_type, ses_message)

        aws_response_dict = get_aws_responses(notification_type)

        notification_status = aws_response_dict['notification_status']

        try:
            # Get service based on SMTP name
            service = services_dao.dao_services_by_partial_smtp_name(source.split('@')[-1])

            # Create a sent notification based on details from the payload
            template = templates_dao.dao_get_template_by_id(current_app.config['SMTP_TEMPLATE_ID'])

            for recipient in recipients:
                message = ''.join(
                    (
                        'A message was sent from: \n',  # noqa: E126
                        source,
                        '\n\n to: \n',
                        recipient,
                        '\n\n on: \n',
                        headers['date'],
                        '\n\n with the subject: \n',
                        headers['subject'],
                    )
                )

                notification = process_notifications.persist_notification(
                    template_id=template.id,
                    template_version=template.version,
                    recipient=recipient,
                    service_id=service.id,
                    personalisation={'subject': headers['subject'], 'message': message},
                    notification_type=EMAIL_TYPE,
                    api_key_id=None,
                    key_type=KEY_TYPE_NORMAL,
                    reply_to_text=recipient,
                    created_at=headers['date'],
                    status=notification_status,
                    reference=ses_message['mail']['messageId'],
                    notification_id=uuid4(),
                )

                if notification_type == 'Complaint':
                    _check_and_queue_complaint_callback_task(*handle_smtp_complaint(ses_message))
                else:
                    check_and_queue_callback_task(notification)

        except NoResultFound:
            reference = ses_message['mail']['messageId']
            current_app.logger.warning(
                'SMTP service not found for reference: %s (update to %s)', reference, notification_status
            )
            return

        statsd_client.incr('callback.ses-smtp.{}'.format(notification_status))

        return True

    except Retry:
        raise

    except Exception as e:
        current_app.logger.exception(e)
        current_app.logger.error('Error processing SES SMTP results: %s', type(e))
        self.retry(queue=QueueNames.RETRY)
