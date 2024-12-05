from datetime import datetime, timedelta
from time import monotonic

from botocore.exceptions import ClientError
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError

from app import db, notify_celery, zendesk_client
from app.celery.tasks import process_job
from app.config import QueueNames, TaskNames
from app.constants import (
    JOB_STATUS_IN_PROGRESS,
    JOB_STATUS_ERROR,
    SMS_TYPE,
    EMAIL_TYPE,
)
from app.dao.invited_org_user_dao import delete_org_invitations_created_more_than_two_days_ago
from app.dao.invited_user_dao import delete_invitations_created_more_than_two_days_ago
from app.dao.jobs_dao import dao_set_scheduled_jobs_to_pending
from app.dao.jobs_dao import dao_update_job
from app.dao.notifications_dao import (
    dao_get_scheduled_notifications,
    set_scheduled_notification_to_processed,
    notifications_not_yet_sent,
    dao_precompiled_letters_still_pending_virus_check,
    dao_old_letters_with_created_status,
)
from app.dao.users_dao import delete_codes_older_created_more_than_a_day_ago
from app.feature_flags import is_feature_enabled, FeatureFlag
from app.integrations.comp_and_pen.scheduled_message_helpers import CompPenMsgHelper
from app.models import Job
from app.notifications.process_notifications import send_notification_to_queue
from app.notifications.send_notifications import lookup_notification_sms_setup_data
from app.v2.errors import JobIncompleteError


@notify_celery.task(name='run-scheduled-jobs')
@statsd(namespace='tasks')
def run_scheduled_jobs():
    try:
        for job in dao_set_scheduled_jobs_to_pending():
            process_job.apply_async([str(job.id)], queue=QueueNames.NOTIFY)
            current_app.logger.info('Job ID {} added to process job queue'.format(job.id))
    except SQLAlchemyError:
        current_app.logger.exception('Failed to run scheduled jobs')
        raise


@notify_celery.task(name='send-scheduled-notifications')
@statsd(namespace='tasks')
def send_scheduled_notifications():
    try:
        scheduled_notifications = dao_get_scheduled_notifications()
        for notification in scheduled_notifications:
            send_notification_to_queue(notification, notification.service.research_mode)
            set_scheduled_notification_to_processed(notification.id)
        current_app.logger.info(
            'Sent {} scheduled notifications to the provider queue'.format(len(scheduled_notifications))
        )
    except SQLAlchemyError:
        current_app.logger.exception('Failed to send scheduled notifications')
        raise


@notify_celery.task(name='delete-verify-codes')
@statsd(namespace='tasks')
def delete_verify_codes():
    try:
        start = datetime.utcnow()
        deleted = delete_codes_older_created_more_than_a_day_ago()
        current_app.logger.info(
            'Delete job started {} finished {} deleted {} verify codes'.format(start, datetime.utcnow(), deleted)
        )
    except SQLAlchemyError:
        current_app.logger.exception('Failed to delete verify codes')
        raise


@notify_celery.task(name='delete-invitations')
@statsd(namespace='tasks')
def delete_invitations():
    try:
        start = datetime.utcnow()
        deleted_invites = delete_invitations_created_more_than_two_days_ago()
        deleted_invites += delete_org_invitations_created_more_than_two_days_ago()
        current_app.logger.info(
            'Delete job started {} finished {} deleted {} invitations'.format(start, datetime.utcnow(), deleted_invites)
        )
    except SQLAlchemyError:
        current_app.logger.exception('Failed to delete invitations')
        raise


@notify_celery.task(name='check-job-status')
@statsd(namespace='tasks')
def check_job_status():
    """
    every x minutes do this check
    select
    from jobs
    where job_status == 'in progress'
    and template_type in ('sms', 'email')
    and scheduled_at or created_at is older that 30 minutes.
    if any results then
        raise error
        process the rows in the csv that are missing (in another task) just do the check here.
    """
    thirty_minutes_ago = datetime.utcnow() - timedelta(minutes=30)
    thirty_five_minutes_ago = datetime.utcnow() - timedelta(minutes=35)

    stmt = (
        select(Job)
        .where(
            Job.job_status == JOB_STATUS_IN_PROGRESS,
            and_(thirty_five_minutes_ago < Job.processing_started, Job.processing_started < thirty_minutes_ago),
        )
        .order_by(Job.processing_started)
    )
    jobs_not_complete_after_30_minutes = db.session.scalars(stmt).all()

    # temporarily mark them as ERROR so that they don't get picked up by future check_job_status tasks
    # if they haven't been re-processed in time.
    job_ids = []
    for job in jobs_not_complete_after_30_minutes:
        job.job_status = JOB_STATUS_ERROR
        dao_update_job(job)
        job_ids.append(str(job.id))

    if job_ids:
        notify_celery.send_task(name=TaskNames.PROCESS_INCOMPLETE_JOBS, args=(job_ids,), queue=QueueNames.NOTIFY)
        raise JobIncompleteError('Job(s) {} have not completed.'.format(job_ids))


@notify_celery.task(name='replay-created-notifications')
@statsd(namespace='tasks')
def replay_created_notifications():
    # if the notification has not be send after 24 hours + 15 minutes, then try to resend.
    resend_created_notifications_older_than = (60 * 60 * 24) + (60 * 15)
    for notification_type in (EMAIL_TYPE, SMS_TYPE):
        notifications_to_resend = notifications_not_yet_sent(resend_created_notifications_older_than, notification_type)

        if len(notifications_to_resend) > 0:
            current_app.logger.info(
                'Sending {} {} notifications '
                'to the delivery queue because the notification '
                'status was created.'.format(len(notifications_to_resend), notification_type)
            )

        for n in notifications_to_resend:
            current_app.logger.info('Replaying notification: %s', n.id)
            send_notification_to_queue(notification=n, research_mode=n.service.research_mode)


@notify_celery.task(name='check-precompiled-letter-state')
@statsd(namespace='tasks')
def check_precompiled_letter_state():
    letters = dao_precompiled_letters_still_pending_virus_check()

    if len(letters) > 0:
        letter_ids = [str(letter.id) for letter in letters]

        msg = '{} precompiled letters have been pending-virus-check for over 90 minutes. ' 'Notifications: {}'.format(
            len(letters), letter_ids
        )

        current_app.logger.exception(msg)

        if current_app.config['NOTIFY_ENVIRONMENT'] in ['live', 'production', 'test']:
            zendesk_client.create_ticket(
                subject='[{}] Letters still pending virus check'.format(current_app.config['NOTIFY_ENVIRONMENT']),
                message=msg,
                ticket_type=zendesk_client.TYPE_INCIDENT,
            )


@notify_celery.task(name='check-templated-letter-state')
@statsd(namespace='tasks')
def check_templated_letter_state():
    letters = dao_old_letters_with_created_status()

    if len(letters) > 0:
        letter_ids = [str(letter.id) for letter in letters]

        msg = (
            "{} letters were created before 17.30 yesterday and still have 'created' status. "
            'Notifications: {}'.format(len(letters), letter_ids)
        )

        current_app.logger.exception(msg)

        if current_app.config['NOTIFY_ENVIRONMENT'] in ['live', 'production', 'test']:
            zendesk_client.create_ticket(
                subject="[{}] Letters still in 'created' status".format(current_app.config['NOTIFY_ENVIRONMENT']),
                message=msg,
                ticket_type=zendesk_client.TYPE_INCIDENT,
            )


@notify_celery.task(name='send-scheduled-comp-and-pen-sms')
@statsd(namespace='tasks')
def send_scheduled_comp_and_pen_sms() -> None:
    start_time = monotonic()
    # this is the agreed upon message per 1 minute limit
    messages_per_min = 90

    # get config info
    dynamodb_table_name = current_app.config['COMP_AND_PEN_DYNAMODB_TABLE_NAME']
    service_id = current_app.config['COMP_AND_PEN_SERVICE_ID']
    template_id = current_app.config['COMP_AND_PEN_TEMPLATE_ID']
    sms_sender_id = current_app.config['COMP_AND_PEN_SMS_SENDER_ID']
    # Perf uses the AWS simulated delivered number
    perf_to_number = current_app.config['COMP_AND_PEN_PERF_TO_NUMBER']

    comp_pen_helper = CompPenMsgHelper(dynamodb_table_name=dynamodb_table_name)

    current_app.logger.debug('send_scheduled_comp_and_pen_sms connecting to dynamodb...')
    try:
        comp_pen_helper._connect_to_dynamodb()
    except ClientError as e:
        current_app.logger.critical(
            'Unable to connect to dynamodb table with name %s - exception: %s', dynamodb_table_name, e
        )
        raise

    current_app.logger.debug('... connected to dynamodb in send_scheduled_comp_and_pen_sms')
    current_app.logger.info('dynamo connection took: %s seconds', monotonic() - start_time)

    # get messages to send
    try:
        comp_and_pen_messages: list = comp_pen_helper.get_dynamodb_comp_pen_messages(messages_per_min)
    except Exception as e:
        current_app.logger.critical(
            'Exception trying to scan dynamodb table for send_scheduled_comp_and_pen_sms exception_type: %s - '
            'exception_message: %s',
            type(e),
            e,
        )
        raise

    current_app.logger.debug('send_scheduled_comp_and_pen_sms list of items from dynamodb: %s', comp_and_pen_messages)

    # only continue if there are messages to update and send
    if comp_and_pen_messages:
        comp_pen_helper.remove_dynamo_item_is_processed(comp_and_pen_messages)

        if is_feature_enabled(FeatureFlag.COMP_AND_PEN_MESSAGES_ENABLED):
            # get the data necessary to send the notifications
            service, template, sms_sender_id = lookup_notification_sms_setup_data(
                service_id, template_id, sms_sender_id
            )

            comp_pen_helper.send_comp_and_pen_sms(
                service=service,
                template=template,
                sms_sender_id=sms_sender_id,
                comp_and_pen_messages=comp_and_pen_messages,
                perf_to_number=perf_to_number,
            )
        else:
            current_app.logger.info('Comp and Pen Notifications not sent to queue (feature flag disabled)')
