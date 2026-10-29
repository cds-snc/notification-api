from datetime import datetime, timedelta
from typing import List, cast

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError

from app import (
    db,
    email_bulk,
    email_normal,
    email_priority,
    notify_celery,
    signer_notification,
    sms_bulk,
    sms_normal,
    sms_priority,
    zendesk_client,
)
from app.celery.tasks import (
    job_complete,
    process_job,
    save_emails,
    save_smss,
    update_in_progress_jobs,
)
from app.config import QueueNames, TaskNames
from app.dao.invited_org_user_dao import (
    delete_org_invitations_created_more_than_two_days_ago,
)
from app.dao.invited_user_dao import delete_invitations_created_more_than_two_days_ago
from app.dao.jobs_dao import dao_set_scheduled_jobs_to_pending, dao_update_job
from app.dao.notifications_dao import (
    dao_delete_scheduled_notification_by_notification_id,
    dao_get_due_scheduled_one_off_notifications,
    dao_get_scheduled_notifications,
    dao_old_letters_with_created_status,
    dao_precompiled_letters_still_pending_virus_check,
    get_notification_count_for_job,
    is_delivery_slow_for_provider,
    notifications_not_yet_sent,
)
from app.dao.provider_details_dao import dao_toggle_sms_provider, get_current_provider
from app.dao.users_dao import delete_codes_older_created_more_than_a_day_ago
from app.encryption import NotificationDictToSign
from app.models import (
    EMAIL_TYPE,
    JOB_STATUS_ERROR,
    JOB_STATUS_IN_PROGRESS,
    SMS_TYPE,
    Job,
    ScheduledNotification,
)
from app.notifications.process_notifications import (
    send_notification_to_queue,
    simulated_recipient,
    triage_notification_to_queues,
)
from app.v2.errors import JobIncompleteError
from celery import Task

# https://stackoverflow.com/questions/63714223/correct-type-annotation-for-a-celery-task
save_smss = cast(Task, save_smss)
save_emails = cast(Task, save_emails)


@notify_celery.task(name="run-scheduled-jobs")
@statsd(namespace="tasks")
def run_scheduled_jobs():
    try:
        for job in dao_set_scheduled_jobs_to_pending():
            process_job.apply_async([str(job.id)], queue=QueueNames.JOBS)
            current_app.logger.info("Job ID {} added to process job queue".format(job.id))
    except SQLAlchemyError:
        current_app.logger.exception("Failed to run scheduled jobs")
        raise


@notify_celery.task(name="mark-jobs-complete")
@statsd(namespace="tasks")
def mark_jobs_complete():
    # query for jobs that are not yet complete
    jobs_not_complete = (
        Job.query.filter(Job.job_status.in_([JOB_STATUS_IN_PROGRESS, JOB_STATUS_ERROR])).order_by(Job.processing_started).all()
    )

    try:
        for job in jobs_not_complete:
            # check if all notifications for that job are sent
            notification_count = get_notification_count_for_job(job.service_id, job.id)

            # if so, mark job as complete
            if notification_count >= job.notification_count:
                job_complete(job)
                current_app.logger.info(f"Job ID {str(job.id)} marked as complete")

    except SQLAlchemyError:
        current_app.logger.exception("Failed to mark jobs complete")
        raise


SCHEDULED_ONE_OFF_NOTIFICATIONS_BATCH_SIZE = 500


@notify_celery.task(name="send-scheduled-notifications")
@statsd(namespace="tasks")
def send_scheduled_notifications():
    try:
        sent_count = _send_due_scheduled_one_off_notifications()
        current_app.logger.info(f"Sent {sent_count} scheduled one-off notifications to the sending queues")

        # Legacy rows, written by an older API instance during a deploy: the notification is already in the
        # notifications table and the ScheduledNotification only has notification_id and scheduled_for.
        scheduled_notifications = dao_get_scheduled_notifications()
        for notification in scheduled_notifications:
            send_notification_to_queue(notification, notification.service.research_mode)
            dao_delete_scheduled_notification_by_notification_id(notification.id)
        current_app.logger.info("Sent {} scheduled notifications to the provider queue".format(len(scheduled_notifications)))
    except SQLAlchemyError:
        current_app.logger.exception("Failed to send scheduled notifications")
        raise


def _send_due_scheduled_one_off_notifications() -> int:
    """Puts scheduled one-off notifications that are due on the same queues as notifications sent straight away, so
    they're added to the notifications table, and counted, when they're sent. Returns the number sent."""
    sent_count = 0
    while True:
        due_notifications = dao_get_due_scheduled_one_off_notifications(SCHEDULED_ONE_OFF_NOTIFICATIONS_BATCH_SIZE)
        try:
            for scheduled_notification in due_notifications:
                notification_to_sign = _scheduled_one_off_notification_to_sign(scheduled_notification)
                if not scheduled_notification.service.active:
                    current_app.logger.warning(
                        f"Scheduled notification {scheduled_notification.notification_id} not sent, "
                        f"service {scheduled_notification.service_id} is inactive"
                    )
                elif notification_to_sign["simulated"]:
                    # Same as notifications sent straight away: simulated recipients aren't persisted or sent
                    current_app.logger.debug(
                        f"Scheduled notification {scheduled_notification.notification_id} not sent, simulated recipient"
                    )
                else:
                    triage_notification_to_queues(
                        scheduled_notification.notification_type,
                        signer_notification.sign(notification_to_sign),
                        scheduled_notification.template,
                    )
                    sent_count += 1
                db.session.delete(scheduled_notification)
            # Also releases the row locks. If publishing fails, the rows are kept and retried on the next run.
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        if len(due_notifications) < SCHEDULED_ONE_OFF_NOTIFICATIONS_BATCH_SIZE:
            return sent_count


def _scheduled_one_off_notification_to_sign(scheduled_notification: ScheduledNotification) -> NotificationDictToSign:
    # Same fields as notifications that are sent straight away, see process_sms_or_email_notification
    notification_to_sign = {
        "id": str(scheduled_notification.notification_id),
        "template": str(scheduled_notification.template_id),
        "service_id": str(scheduled_notification.service_id),
        "template_version": str(scheduled_notification.template_version),
        "to": str(scheduled_notification.to),
        "personalisation": scheduled_notification.personalisation,
        "simulated": simulated_recipient(scheduled_notification.to, scheduled_notification.notification_type),
        "api_key": str(scheduled_notification.api_key_id) if scheduled_notification.api_key_id else None,
        "key_type": scheduled_notification.key_type,
        "client_reference": scheduled_notification.client_reference,
        "reply_to_text": scheduled_notification.reply_to_text,
    }
    return cast(NotificationDictToSign, notification_to_sign)


@notify_celery.task(name="delete-verify-codes")
@statsd(namespace="tasks")
def delete_verify_codes():
    try:
        start = datetime.utcnow()
        deleted = delete_codes_older_created_more_than_a_day_ago()
        current_app.logger.info(
            "Delete job started {} finished {} deleted {} verify codes".format(start, datetime.utcnow(), deleted)
        )
    except SQLAlchemyError:
        current_app.logger.exception("Failed to delete verify codes")
        raise


@notify_celery.task(name="delete-invitations")
@statsd(namespace="tasks")
def delete_invitations():
    try:
        start = datetime.utcnow()
        deleted_invites = delete_invitations_created_more_than_two_days_ago()
        deleted_invites += delete_org_invitations_created_more_than_two_days_ago()
        current_app.logger.info(
            "Delete job started {} finished {} deleted {} invitations".format(start, datetime.utcnow(), deleted_invites)
        )
    except SQLAlchemyError:
        current_app.logger.exception("Failed to delete invitations")
        raise


@notify_celery.task(name="switch-current-sms-provider-on-slow-delivery")
@statsd(namespace="tasks")
def switch_current_sms_provider_on_slow_delivery():
    """
    Switch providers if at least 30% of notifications took more than four minutes to be delivered
    in the last ten minutes. Search from the time we last switched to the current provider.
    """
    current_provider = get_current_provider("sms")
    if current_provider.updated_at > datetime.utcnow() - timedelta(minutes=10):
        current_app.logger.info("Slow delivery notifications provider switched less than 10 minutes ago.")
        return
    slow_delivery_notifications = is_delivery_slow_for_provider(
        provider=current_provider.identifier,
        threshold=0.3,
        created_at=datetime.utcnow() - timedelta(minutes=10),
        delivery_time=timedelta(minutes=4),
    )

    if slow_delivery_notifications:
        current_app.logger.warning("Slow delivery notifications detected for provider {}".format(current_provider.identifier))

        dao_toggle_sms_provider(current_provider.identifier)


@notify_celery.task(name="check-job-status")
@statsd(namespace="tasks")
def check_job_status():
    """
    every x minutes do this check
    select
    from jobs
    where job_status == 'in progress'
    and template_type in ('sms', 'email')
    and scheduled_at or created_at is older than 30 minutes.
    if any results then
        raise error
        process the rows in the csv that are missing (in another task) just do the check here.
    """
    minutes_ago_30 = datetime.utcnow() - timedelta(minutes=30)
    minutes_ago_35 = datetime.utcnow() - timedelta(minutes=35)
    update_in_progress_jobs()

    jobs_not_complete_after_30_minutes = (
        Job.query.filter(
            Job.job_status == JOB_STATUS_IN_PROGRESS,
            and_(
                minutes_ago_35 < Job.updated_at,
                Job.updated_at < minutes_ago_30,
            ),
        )
        .order_by(Job.updated_at)
        .all()
    )

    # temporarily mark them as ERROR so that they don't get picked up by future check_job_status tasks
    # if they haven't been re-processed in time.
    job_ids: List[str] = []  # type: ignore
    for job in jobs_not_complete_after_30_minutes:
        job.job_status = JOB_STATUS_ERROR
        dao_update_job(job)
        job_ids.append(str(job.id))

    if job_ids:
        notify_celery.send_task(
            name=TaskNames.PROCESS_INCOMPLETE_JOBS,
            args=(job_ids,),
            queue=QueueNames.JOBS,
        )
        raise JobIncompleteError("Job(s) {} have not completed.".format(job_ids))


@notify_celery.task(name="replay-created-notifications")
@statsd(namespace="tasks")
def replay_created_notifications():
    # if the notification has not be send after 4 hours + 15 minutes, then try to resend.
    resend_created_notifications_older_than = (60 * 60 * 4) + (60 * 15)
    for notification_type in (EMAIL_TYPE, SMS_TYPE):
        notifications_to_resend = notifications_not_yet_sent(resend_created_notifications_older_than, notification_type)

        if len(notifications_to_resend) > 0:
            current_app.logger.info(
                "Sending {} {} notifications " "to the delivery queue because the notification " "status was created.".format(
                    len(notifications_to_resend), notification_type
                )
            )

        for n in notifications_to_resend:
            send_notification_to_queue(notification=n, research_mode=n.service.research_mode)


@notify_celery.task(name="check-precompiled-letter-state")
@statsd(namespace="tasks")
def check_precompiled_letter_state():
    letters = dao_precompiled_letters_still_pending_virus_check()

    if len(letters) > 0:
        letter_ids = [str(letter.id) for letter in letters]

        msg = "{} precompiled letters have been pending-virus-check for over 90 minutes. " "Notifications: {}".format(
            len(letters), letter_ids
        )

        current_app.logger.exception(msg)

        if current_app.config["NOTIFY_ENVIRONMENT"] in ["live", "production", "test"]:
            zendesk_client.create_ticket(
                subject="[{}] Letters still pending virus check".format(current_app.config["NOTIFY_ENVIRONMENT"]),
                message=msg,
                ticket_type=zendesk_client.TYPE_INCIDENT,
            )


@notify_celery.task(name="check-templated-letter-state")
@statsd(namespace="tasks")
def check_templated_letter_state():
    letters = dao_old_letters_with_created_status()

    if len(letters) > 0:
        letter_ids = [str(letter.id) for letter in letters]

        msg = "{} letters were created before 17.30 yesterday and still have 'created' status. " "Notifications: {}".format(
            len(letters), letter_ids
        )

        current_app.logger.exception(msg)

        if current_app.config["NOTIFY_ENVIRONMENT"] in ["live", "production", "test"]:
            zendesk_client.create_ticket(
                subject="[{}] Letters still in 'created' status".format(current_app.config["NOTIFY_ENVIRONMENT"]),
                message=msg,
                ticket_type=zendesk_client.TYPE_INCIDENT,
            )


@notify_celery.task(name="in-flight-to-inbox")
@statsd(namespace="tasks")
def recover_expired_notifications():
    sms_bulk.expire_inflights()
    sms_normal.expire_inflights()
    sms_priority.expire_inflights()
    email_bulk.expire_inflights()
    email_normal.expire_inflights()
    email_priority.expire_inflights()


@notify_celery.task(name="beat-inbox-email-normal")
@statsd(namespace="tasks")
def beat_inbox_email_normal():
    """
    The function acts as a beat schedule to a list of notifications in the queue.
    The post_api will push all the notifications with normal priority into the above list.
    The heartbeat with check the list (list#1) until it is non-emtpy and move the notifications in a batch
    to another list(list#2). The heartbeat will then call a job that saves list#2 to the DB
    and actually sends the email for each notification saved.
    """
    receipt_id_email, list_of_email_notifications = email_normal.poll()

    while list_of_email_notifications:
        save_emails.apply_async((None, list_of_email_notifications, receipt_id_email), queue=QueueNames.NORMAL_DATABASE)
        current_app.logger.info(f"Batch saving with Normal Priority: email receipt {receipt_id_email} sent to in-flight.")
        receipt_id_email, list_of_email_notifications = email_normal.poll()


@notify_celery.task(name="beat-inbox-email-bulk")
@statsd(namespace="tasks")
def beat_inbox_email_bulk():
    """
    The function acts as a beat schedule to a list of notifications in the queue.
    The post_api will push all the notifications with bulk priority into the above list.
    The heartbeat with check the list (list#1) until it is non-emtpy and move the notifications in a batch
    to another list(list#2). The heartbeat will then call a job that saves list#2 to the DB
    and actually sends the email for each notification saved.
    """
    receipt_id_email, list_of_email_notifications = email_bulk.poll()

    while list_of_email_notifications:
        save_emails.apply_async((None, list_of_email_notifications, receipt_id_email), queue=QueueNames.BULK_DATABASE)
        current_app.logger.info(f"Batch saving with Bulk Priority: email receipt {receipt_id_email} sent to in-flight.")
        receipt_id_email, list_of_email_notifications = email_bulk.poll()


@notify_celery.task(name="beat-inbox-email-priority")
@statsd(namespace="tasks")
def beat_inbox_email_priority():
    """
    The function acts as a beat schedule to a list of notifications in the queue.
    The post_api will push all the notifications with priority into the above list.
    The heartbeat with check the list (list#1) until it is non-emtpy and move the notifications in a batch
    to another list(list#2). The heartbeat will then call a job that saves list#2 to the DB
    and actually sends the email for each notification saved.
    """
    receipt_id_email, list_of_email_notifications = email_priority.poll()

    while list_of_email_notifications:
        save_emails.apply_async((None, list_of_email_notifications, receipt_id_email), queue=QueueNames.PRIORITY_DATABASE)
        current_app.logger.info(f"Batch saving with Priority: email receipt {receipt_id_email} sent to in-flight.")
        receipt_id_email, list_of_email_notifications = email_priority.poll()


@notify_celery.task(name="beat-inbox-sms-normal")
@statsd(namespace="tasks")
def beat_inbox_sms_normal():
    """
    The function acts as a beat schedule to a list of notifications in the queue.
    The post_api will push all the notifications of normal priority into the above list.
    The heartbeat with check the list (list#1) until it is non-emtpy and move the notifications in a batch
    to another list(list#2). The heartbeat will then call a job that saves list#2 to the DB
    and actually sends the sms for each notification saved.
    """
    receipt_id_sms, list_of_sms_notifications = sms_normal.poll()

    while list_of_sms_notifications:
        save_smss.apply_async((None, list_of_sms_notifications, receipt_id_sms), queue=QueueNames.NORMAL_DATABASE)
        current_app.logger.info(f"Batch saving with Normal Priority: SMS receipt {receipt_id_sms} sent to in-flight.")
        receipt_id_sms, list_of_sms_notifications = sms_normal.poll()


@notify_celery.task(name="beat-inbox-sms-bulk")
@statsd(namespace="tasks")
def beat_inbox_sms_bulk():
    """
    The function acts as a beat schedule to a list of notifications in the queue.
    The post_api will push all the notifications of bulk priority into the above list.
    The heartbeat with check the list (list#1) until it is non-emtpy and move the notifications in a batch
    to another list(list#2). The heartbeat will then call a job that saves list#2 to the DB
    and actually sends the sms for each notification saved.
    """
    receipt_id_sms, list_of_sms_notifications = sms_bulk.poll()

    while list_of_sms_notifications:
        save_smss.apply_async((None, list_of_sms_notifications, receipt_id_sms), queue=QueueNames.BULK_DATABASE)
        current_app.logger.info(f"Batch saving with Bulk Priority: SMS receipt {receipt_id_sms} sent to in-flight.")
        receipt_id_sms, list_of_sms_notifications = sms_bulk.poll()


@notify_celery.task(name="beat-inbox-sms-priority")
@statsd(namespace="tasks")
def beat_inbox_sms_priority():
    """
    The function acts as a beat schedule to a list of notifications in the queue.
    The post_api will push all the notifications of priority into the above list.
    The heartbeat with check the list (list#1) until it is non-emtpy and move the notifications in a batch
    to another list(list#2). The heartbeat will then call a job that saves list#2 to the DB
    and actually sends the sms for each notification saved.
    """
    receipt_id_sms, list_of_sms_notifications = sms_priority.poll()

    while list_of_sms_notifications:
        save_smss.apply_async((None, list_of_sms_notifications, receipt_id_sms), queue=QueueNames.PRIORITY_DATABASE)
        current_app.logger.info(f"Batch saving with Priority: SMS receipt {receipt_id_sms} sent to in-flight.")
        receipt_id_sms, list_of_sms_notifications = sms_priority.poll()
