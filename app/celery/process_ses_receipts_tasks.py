from datetime import datetime, timedelta

import iso8601
from celery.exceptions import Retry
from flask import (
    current_app,
    json,
)
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound

from app import notify_celery, statsd_client
from app.config import QueueNames
from app.clients.email.aws_ses import get_aws_responses
from app.dao import notifications_dao, services_dao, templates_dao
from app.models import NOTIFICATION_SENDING, NOTIFICATION_PENDING, EMAIL_TYPE, KEY_TYPE_NORMAL
from app.notifications import process_notifications
from app.notifications.callbacks import _check_and_queue_callback_task
from app.notifications.notifications_ses_callback import (
    determine_notification_bounce_type,
    handle_complaint,
    handle_smtp_complaint,
    _check_and_queue_complaint_callback_task,
)


# Celery rate limits are per worker instance and not a global rate limit.
# https://docs.celeryproject.org/en/stable/userguide/tasks.html#Task.rate_limit
# This queue is consumed by 6 Celery instances with 4 workers in production.
# The maximum throughput is therefore 6 instances * 4 workers * 30 tasks = 720 tasks / minute
# if we set rate_limit="30/m" on the Celery task
@notify_celery.task(
    bind=True,
    name="process-ses-result",
    max_retries=5,
    default_retry_delay=300,
)
@statsd(namespace="tasks")
def process_ses_results(self, response):
    try:
        ses_message = json.loads(response['Message'])
        notification_type = ses_message['notificationType']

        if notification_type == 'Bounce':
            notification_type = determine_notification_bounce_type(notification_type, ses_message)
        elif notification_type == 'Complaint':
            _check_and_queue_complaint_callback_task(*handle_complaint(ses_message))
            return True

        aws_response_dict = get_aws_responses(notification_type)

        notification_status = aws_response_dict['notification_status']
        reference = ses_message['mail']['messageId']

        try:
            notification = notifications_dao.dao_get_notification_by_reference(reference)
        except NoResultFound:
            message_time = iso8601.parse_date(ses_message['mail']['timestamp']).replace(tzinfo=None)
            if datetime.utcnow() - message_time < timedelta(minutes=5):
                self.retry(queue=QueueNames.RETRY)
            else:
                current_app.logger.warning(
                    "notification not found for reference: {} (update to {})".format(reference, notification_status)
                )
            return

        if notification.status not in {NOTIFICATION_SENDING, NOTIFICATION_PENDING}:
            notifications_dao._duplicate_update_warning(notification, notification_status)
            return

        notifications_dao._update_notification_status(notification=notification, status=notification_status)

        if not aws_response_dict['success']:
            current_app.logger.info(
                "SES delivery failed: notification id {} and reference {} has error found. Status {}".format(
                    notification.id, reference, aws_response_dict['message']
                )
            )
        else:
            current_app.logger.info('SES callback return status of {} for notification: {}'.format(
                notification_status, notification.id
            ))

        statsd_client.incr('callback.ses.{}'.format(notification_status))

        if notification.sent_at:
            statsd_client.timing_with_dates('callback.ses.elapsed-time', datetime.utcnow(), notification.sent_at)

        _check_and_queue_callback_task(notification)

        return True

    except Retry:
        raise

    except Exception as e:
        current_app.logger.exception('Error processing SES results: {}'.format(type(e)))
        self.retry(queue=QueueNames.RETRY)


@notify_celery.task(
    bind=True,
    name="process-ses-smtp-results",
    max_retries=5,
    default_retry_delay=300)
@statsd(namespace="tasks")
def process_ses_smtp_results(self, response):
    try:
        ses_message = json.loads(response['Message'])

        notification_type = ses_message['notificationType']
        headers = ses_message['mail']['commonHeaders']
        source = ses_message['mail']['source']
        recipients = ses_message['mail']['destination']

        if notification_type == 'Bounce':
            notification_type = determine_notification_bounce_type(notification_type, ses_message)

        aws_response_dict = get_aws_responses(notification_type)

        notification_status = aws_response_dict['notification_status']

        try:
            # Get service based on SMTP name
            service = services_dao.dao_services_by_partial_smtp_name(source.split("@")[-1])

            # Create a sent notification based on details from the payload
            template = templates_dao.dao_get_template_by_id(current_app.config['SMTP_TEMPLATE_ID'])

            for recipient in recipients:

                message = "".join((
                                'A message was sent from: \n',  # noqa: E126
                                source,
                                '\n\n to: \n',
                                recipient,
                                '\n\n on: \n',
                                headers["date"],
                                '\n\n with the subject: \n',
                                headers["subject"]))

                notification = process_notifications.persist_notification(
                    template_id=template.id,
                    template_version=template.version,
                    recipient=recipient,
                    service=service,
                    personalisation={
                        'subject': headers["subject"],
                        'message': message
                    },
                    notification_type=EMAIL_TYPE,
                    api_key_id=None,
                    key_type=KEY_TYPE_NORMAL,
                    reply_to_text=recipient,
                    created_at=headers["date"],
                    status=notification_status,
                    reference=ses_message['mail']['messageId']
                )

                if notification_type == 'Complaint':
                    _check_and_queue_complaint_callback_task(*handle_smtp_complaint(ses_message))
                else:
                    _check_and_queue_callback_task(notification)

        except NoResultFound:
            reference = ses_message['mail']['messageId']
            current_app.logger.warning(
                "SMTP service not found for reference: {} (update to {})".format(reference, notification_status)
            )
            return

        statsd_client.incr('callback.ses-smtp.{}'.format(notification_status))

        return True

    except Retry:
        raise

    except Exception as e:
        current_app.logger.exception('Error processing SES SMTP results: {}'.format(type(e)))
        self.retry(queue=QueueNames.RETRY)
