import json
from collections import defaultdict, namedtuple
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import current_app
from more_itertools import chunked
from notifications_utils.columns import Row
from notifications_utils.recipients import RecipientCSV
from notifications_utils.statsd_decorators import statsd
from notifications_utils.template import SMSMessageTemplate, WithSubjectTemplate
from notifications_utils.timezones import convert_utc_to_local_timezone
from requests import HTTPError, RequestException, request
from sqlalchemy.exc import SQLAlchemyError

from app import (
    DATETIME_FORMAT,
    create_random_identifier,
    create_uuid,
    encryption,
    notify_celery,
    statsd_client,
)
from app.aws import s3
from app.celery import (  # noqa: F401
    letters_pdf_tasks,
    process_sns_receipts_tasks,
    provider_tasks,
    research_mode_tasks,
)
from app.config import Config, QueueNames
from app.dao.daily_sorted_letter_dao import dao_create_or_update_daily_sorted_letter
from app.dao.inbound_sms_dao import dao_get_inbound_sms_by_id
from app.dao.jobs_dao import dao_get_job_by_id, dao_update_job
from app.dao.notifications_dao import (
    dao_get_last_notification_added_for_job_id,
    dao_get_notification_history_by_reference,
    dao_update_notifications_by_reference,
    get_notification_by_id,
    update_notification_status_by_reference,
)
from app.dao.provider_details_dao import get_current_provider
from app.dao.service_email_reply_to_dao import dao_get_reply_to_by_id
from app.dao.service_inbound_api_dao import get_service_inbound_api_for_service
from app.dao.service_sms_sender_dao import dao_get_service_sms_senders_by_id
from app.dao.services_dao import (
    dao_fetch_service_by_id,
    fetch_todays_total_message_count,
)
from app.dao.templates_dao import dao_get_template_by_id
from app.exceptions import DVLAException, NotificationTechnicalFailureException
from app.models import (
    DVLA_RESPONSE_STATUS_SENT,
    EMAIL_TYPE,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FINISHED,
    JOB_STATUS_IN_PROGRESS,
    JOB_STATUS_PENDING,
    JOB_STATUS_SENDING_LIMITS_EXCEEDED,
    KEY_TYPE_NORMAL,
    LETTER_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_RETURNED_LETTER,
    NOTIFICATION_SENDING,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    SMS_TYPE,
    DailySortedLetter,
    Job,
    Service,
    Template,
)
from app.notifications.process_notifications import (
    persist_notification,
    persist_notifications,
    send_notification_to_queue,
)
from app.notifications.validators import check_service_over_daily_message_limit
from app.service.utils import service_allowed_to_send_to
from app.utils import get_csv_max_rows


@notify_celery.task(name="process-job")
@statsd(namespace="tasks")
def process_job(job_id):
    start = datetime.utcnow()
    job = dao_get_job_by_id(job_id)

    if job.job_status != JOB_STATUS_PENDING:
        return

    service = job.service

    if not service.active:
        job.job_status = JOB_STATUS_CANCELLED
        dao_update_job(job)
        current_app.logger.warning("Job {} has been cancelled, service {} is inactive".format(job_id, service.id))
        return

    if __sending_limits_for_job_exceeded(service, job, job_id):
        return

    job.job_status = JOB_STATUS_IN_PROGRESS
    job.processing_started = start
    dao_update_job(job)

    # Record StatsD stats to compute SLOs
    job_start = job.scheduled_for or job.created_at
    statsd_client.timing_with_dates("job.processing-start-delay", job.processing_started, job_start)

    db_template = dao_get_template_by_id(job.template_id, job.template_version)

    TemplateClass = get_template_class(db_template.template_type)
    template = TemplateClass(db_template.__dict__)

    current_app.logger.debug("Starting job {} processing {} notifications".format(job_id, job.notification_count))

    csv = get_recipient_csv(job, template)

    if Config.FF_BATCH_INSERTION:
        rows = csv.get_rows()
        for result in chunked(rows, Config.BATCH_INSERTION_CHUNK_SIZE):
            process_rows(result, template, job, service)
    else:
        for row in csv.get_rows():
            process_row(row, template, job, service)

    job_complete(job, start=start)


def job_complete(job: Job, resumed=False, start=None):
    job.job_status = JOB_STATUS_FINISHED

    finished = datetime.utcnow()
    job.processing_finished = finished
    dao_update_job(job)

    if resumed:
        current_app.logger.info("Resumed Job {} completed at {}".format(job.id, job.created_at))
    else:
        current_app.logger.info(
            "Job {} created at {} started at {} finished at {}".format(job.id, job.created_at, start, finished)
        )


def process_row(row: Row, template: Template, job: Job, service: Service):
    template_type = template.template_type
    encrypted = encryption.encrypt(
        {
            "api_key": job.api_key_id and str(job.api_key_id),
            "template": str(template.id),
            "template_version": job.template_version,
            "job": str(job.id),
            "to": row.recipient,
            "row_number": row.index,
            "personalisation": dict(row.personalisation),
            "queue": queue_to_use(job.notification_count),
        }
    )

    notification_id = create_uuid()

    sender_id = str(job.sender_id) if job.sender_id else None

    send_fns = {SMS_TYPE: save_sms, EMAIL_TYPE: save_email, LETTER_TYPE: save_letter}

    send_fn = send_fns[template_type]

    task_kwargs = {}
    if sender_id:
        task_kwargs["sender_id"] = sender_id

    # the same_sms and save_email task are going to be using template and service objects from cache
    # these objects are transient and will not have relationships loaded
    if service_allowed_to_send_to(row.recipient, service, KEY_TYPE_NORMAL):
        send_fn.apply_async(
            (
                str(service.id),
                notification_id,
                encrypted,
            ),
            task_kwargs,
            queue=QueueNames.DATABASE if not service.research_mode else QueueNames.RESEARCH_MODE,
        )
    else:
        current_app.logger.debug("SMS {} failed as restricted service".format(notification_id))


def process_rows(rows: List, template: Template, job: Job, service: Service):
    template_type = template.template_type
    sender_id = str(job.sender_id) if job.sender_id else None
    encrypted_smss: List[Any] = []
    encrypted_emails: List[Any] = []
    encrypted_letters: List[Any] = []

    for row in rows:
        if service_allowed_to_send_to(row.recipient, service, KEY_TYPE_NORMAL):
            encrypted_row = encryption.encrypt(
                {
                    "api_key": job.api_key_id and str(job.api_key_id),
                    "template": str(template.id),
                    "template_version": job.template_version,
                    "job": str(job.id),
                    "to": row.recipient,
                    "row_number": row.index,
                    "personalisation": dict(row.personalisation),
                    "queue": queue_to_use(job.notification_count),
                    "sender_id": sender_id,
                }
            )
            if template_type == SMS_TYPE:
                encrypted_smss.append(encrypted_row)
            if template_type == EMAIL_TYPE:
                encrypted_emails.append(encrypted_row)
            if template_type == LETTER_TYPE:
                encrypted_letters.append(encrypted_letters)

    # the same_sms and save_email task are going to be using template and service objects from cache
    # these objects are transient and will not have relationships loaded
    if encrypted_smss:
        save_smss.apply_async(
            (str(service.id), encrypted_smss),
            queue=QueueNames.DATABASE if not service.research_mode else QueueNames.RESEARCH_MODE,
        )
    if encrypted_emails:
        save_emails.apply_async(
            (str(service.id), encrypted_emails),
            queue=QueueNames.DATABASE if not service.research_mode else QueueNames.RESEARCH_MODE,
        )
    if encrypted_letters:
        save_letters.apply_async(
            (str(service.id), encrypted_letters),
            queue=QueueNames.DATABASE if not service.research_mode else QueueNames.RESEARCH_MODE,
        )


def __sending_limits_for_job_exceeded(service, job: Job, job_id):
    total_sent = fetch_todays_total_message_count(service.id)

    if total_sent + job.notification_count > service.message_limit:
        job.job_status = JOB_STATUS_SENDING_LIMITS_EXCEEDED
        job.processing_finished = datetime.utcnow()
        dao_update_job(job)
        current_app.logger.info(
            "Job {} size {} error. Sending limits {} exceeded".format(job_id, job.notification_count, service.message_limit)
        )
        return True
    return False


@notify_celery.task(bind=True, name="save-smss", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def save_smss(self, service_id: str, encrypted_notifications: List[Any]):
    """
    Function that is a job, that takes a list of encrypted notifications and stores
    them in the DB and then sends the notification to the queue.

    """
    decrypted_notifications: List[Any] = []
    notification_id_queue: Dict = {}
    for encrypted_notification in encrypted_notifications:
        notification = encryption.decrypt(encrypted_notification)
        service = dao_fetch_service_by_id(service_id, use_cache=True)
        template = dao_get_template_by_id(
            notification.get("template"), version=notification.get("template_version"), use_cache=True
        )
        sender_id = notification.get("sender_id")
        notification_id = create_uuid()
        notification["notification_id"] = notification_id
        reply_to_text = ""  # type: ignore
        if sender_id:
            reply_to_text = dao_get_service_sms_senders_by_id(service_id, sender_id).sms_sender
        if isinstance(template, tuple):
            template = template[0]
        # if the template is obtained from cache a tuple will be returned where
        # the first element is the Template object and the second the template cache data
        # in the form of a dict
        elif isinstance(template, tuple):
            reply_to_text = template[1].get("reply_to_text")  # type: ignore
            template = template[0]
        else:
            reply_to_text = template.get_reply_to_text()  # type: ignore

        # if the service is obtained from cache a tuple will be returned where
        # the first element is the Service object and the second the service cache data
        # in the form of a dict
        if isinstance(service, tuple):
            service = service[0]

        notification["reply_to_text"] = reply_to_text
        notification["service"] = service
        notification["key_type"] = notification.get("key_type", KEY_TYPE_NORMAL)
        notification["template_id"] = template.id
        notification["template_version"] = template.version
        notification["recipient"] = notification.get("to")
        notification["personalisation"] = notification.get("personalisation")
        notification["notification_type"] = SMS_TYPE
        notification["simulated"] = notification.get("simulated", None)
        notification["api_key_id"] = notification.get("api_key", None)
        notification["created_at"] = datetime.utcnow()
        notification["job_id"] = notification.get("job", None)
        notification["job_row_number"] = notification.get("row_number", None)
        decrypted_notifications.append(notification)
        notification_id_queue[notification_id] = notification.get("queue")

    try:
        # this task is used by two main things... process_job and process_sms_or_email_notification
        # if the data is not present in the encrypted data then fallback on whats needed for process_job
        saved_notifications = persist_notifications(decrypted_notifications)

    except SQLAlchemyError as e:
        handle_list_of_exception(self, decrypted_notifications, e)

    for notification in saved_notifications:
        check_service_over_daily_message_limit(KEY_TYPE_NORMAL, service)
        research_mode = service.research_mode  # type: ignore
        queue = notification_id_queue.get(notification.id) or template.queue_to_use()  # type: ignore
        send_notification_to_queue(
            notification,
            research_mode,
            queue=queue,
        )

        current_app.logger.debug(
            "SMS {} created at {} for job {}".format(
                notification.id,
                notification.created_at,
                notification.job,
            )
        )


@notify_celery.task(bind=True, name="save-sms", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def save_sms(self, service_id, notification_id, encrypted_notification, sender_id=None):
    notification = encryption.decrypt(encrypted_notification)
    service = dao_fetch_service_by_id(service_id, use_cache=True)
    template = dao_get_template_by_id(notification["template"], version=notification["template_version"], use_cache=True)

    if sender_id:
        reply_to_text = dao_get_service_sms_senders_by_id(service_id, sender_id).sms_sender
        if isinstance(template, tuple):
            template = template[0]
    # if the template is obtained from cache a tuple will be returned where
    # the first element is the Template object and the second the template cache data
    # in the form of a dict
    elif isinstance(template, tuple):
        reply_to_text = template[1].get("reply_to_text")
        template = template[0]
    else:
        reply_to_text = template.get_reply_to_text()

    # if the service is obtained from cache a tuple will be returned where
    # the first element is the Service object and the second the service cache data
    # in the form of a dict
    if isinstance(service, tuple):
        service = service[0]

    check_service_over_daily_message_limit(KEY_TYPE_NORMAL, service)

    try:
        # this task is used by two main things... process_job and process_sms_or_email_notification
        # if the data is not present in the encrypted data then fallback on whats needed for process_job
        saved_notification = persist_notification(
            notification_id=notification.get("id", notification_id),
            template_id=notification["template"],
            template_version=notification["template_version"],
            recipient=notification["to"],
            service=service,
            personalisation=notification.get("personalisation"),
            notification_type=SMS_TYPE,
            simulated=notification.get("simulated", None),
            api_key_id=notification.get("api_key", None),
            key_type=notification.get("key_type", KEY_TYPE_NORMAL),
            created_at=datetime.utcnow(),
            job_id=notification.get("job", None),
            job_row_number=notification.get("row_number", None),
            reply_to_text=reply_to_text,
        )

        send_notification_to_queue(
            saved_notification,
            service.research_mode,
            queue=notification.get("queue") or template.queue_to_use(),
        )

        current_app.logger.debug(
            "SMS {} created at {} for job {}".format(
                saved_notification.id,
                saved_notification.created_at,
                notification.get("job", None),
            )
        )

    except SQLAlchemyError as e:
        handle_exception(self, notification, notification_id, e)


@notify_celery.task(bind=True, name="save-emails", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def save_emails(self, service_id: str, encrypted_notifications: List[Any]):
    """
    Function that is a job, that takes a list of encrypted notifications and stores
    them in the DB and then sends the notification to the queue.

    """
    decrypted_notifications: List[Any] = []
    notification_id_queue: Dict = {}
    for encrypted_notification in encrypted_notifications:
        notification = encryption.decrypt(encrypted_notification)
        service = dao_fetch_service_by_id(service_id, use_cache=True)
        template = dao_get_template_by_id(
            notification.get("template"), version=notification.get("template_version"), use_cache=True
        )
        sender_id = notification.get("sender_id")
        notification_id = create_uuid()
        notification["notification_id"] = notification_id
        reply_to_text = ""  # type: ignore
        if sender_id:
            reply_to_text = dao_get_reply_to_by_id(service_id, sender_id).email_address
        if isinstance(template, tuple):
            template = template[0]
        # if the template is obtained from cache a tuple will be returned where
        # the first element is the Template object and the second the template cache data
        # in the form of a dict
        elif isinstance(template, tuple):
            reply_to_text = template[1].get("reply_to_text")  # type: ignore
            template = template[0]
        else:
            reply_to_text = template.get_reply_to_text()  # type: ignore

        # if the service is obtained from cache a tuple will be returned where
        # the first element is the Service object and the second the service cache data
        # in the form of a dict
        if isinstance(service, tuple):
            service = service[0]

        notification["reply_to_text"] = reply_to_text
        notification["service"] = service
        notification["key_type"] = notification.get("key_type", KEY_TYPE_NORMAL)
        notification["template_id"] = template.id
        notification["template_version"] = template.version
        notification["recipient"] = notification.get("to")
        notification["personalisation"] = notification.get("personalisation")
        notification["notification_type"] = EMAIL_TYPE
        notification["simulated"] = notification.get("simulated", None)
        notification["api_key_id"] = notification.get("api_key", None)
        notification["created_at"] = datetime.utcnow()
        notification["job_id"] = notification.get("job", None)
        notification["job_row_number"] = notification.get("row_number", None)
        decrypted_notifications.append(notification)
        notification_id_queue[notification_id] = notification.get("queue")

    try:
        # this task is used by two main things... process_job and process_sms_or_email_notification
        # if the data is not present in the encrypted data then fallback on whats needed for process_job
        saved_notifications = persist_notifications(decrypted_notifications)
    except SQLAlchemyError as e:
        handle_list_of_exception(self, decrypted_notifications, e)

    if saved_notifications:
        for notification in saved_notifications:
            check_service_over_daily_message_limit(KEY_TYPE_NORMAL, service)
            research_mode = service.research_mode  # type: ignore
            queue = notification_id_queue.get(notification.id) or template.queue_to_use()  # type: ignore
            send_notification_to_queue(
                notification,
                research_mode,
                queue,
            )

            current_app.logger.debug(
                "SMS {} created at {} for job {}".format(
                    notification.id,
                    notification.created_at,
                    notification.job,
                )
            )


@notify_celery.task(bind=True, name="save-email", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def save_email(self, service_id, notification_id, encrypted_notification, sender_id=None):
    notification = encryption.decrypt(encrypted_notification)
    service = dao_fetch_service_by_id(service_id, use_cache=True)
    template = dao_get_template_by_id(notification["template"], version=notification["template_version"], use_cache=True)

    if sender_id:
        reply_to_text = dao_get_reply_to_by_id(service_id, sender_id).email_address
        if isinstance(template, tuple):
            template = template[0]
    # if the template is obtained from cache a tuple will be returned where
    # the first element is the Template object and the second the template cache data
    # in the form of a dict
    elif isinstance(template, tuple):
        reply_to_text = template[1].get("reply_to_text")
        template = template[0]
    else:
        reply_to_text = template.get_reply_to_text()

    # if the service is obtained from cache a tuple will be returned where
    # the first element is the Service object and the second the service cache data
    # in the form of a dict
    if isinstance(service, tuple):
        service = service[0]

    check_service_over_daily_message_limit(notification.get("key_type", KEY_TYPE_NORMAL), service)

    try:
        # this task is used by two main things... process_job and process_sms_or_email_notification
        # if the data is not present in the encrypted data then fallback on whats needed for process_job
        saved_notification = persist_notification(
            notification_id=notification.get("id", notification_id),
            template_id=notification["template"],
            template_version=notification["template_version"],
            recipient=notification["to"],
            service=service,
            personalisation=notification.get("personalisation"),
            notification_type=EMAIL_TYPE,
            api_key_id=notification.get("api_key", None),
            key_type=notification.get("key_type", KEY_TYPE_NORMAL),
            created_at=datetime.utcnow(),
            job_id=notification.get("job", None),
            simulated=notification.get("simulated", None),
            job_row_number=notification.get("row_number", None),
            reply_to_text=reply_to_text,
            client_reference=notification.get("client_reference", None),
        )
        send_notification_to_queue(
            saved_notification,
            service.research_mode,
            queue=notification.get("queue") or template.queue_to_use(),
        )

        current_app.logger.debug("Email {} created at {}".format(saved_notification.id, saved_notification.created_at))
    except SQLAlchemyError as e:
        handle_exception(self, notification, notification_id, e)


@notify_celery.task(bind=True, name="save-letter", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def save_letters(self, encrpyted_notifications):
    pass


@notify_celery.task(bind=True, name="save-letter", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def save_letter(
    self,
    service_id,
    notification_id,
    encrypted_notification,
):
    notification = encryption.decrypt(encrypted_notification)

    # we store the recipient as just the first item of the person's address
    recipient = notification["personalisation"]["addressline1"]

    service = dao_fetch_service_by_id(service_id)
    template = dao_get_template_by_id(notification["template"], version=notification["template_version"])

    check_service_over_daily_message_limit(KEY_TYPE_NORMAL, service)

    try:
        # if we don't want to actually send the letter, then start it off in SENDING so we don't pick it up
        status = NOTIFICATION_CREATED if not service.research_mode else NOTIFICATION_SENDING

        saved_notification = persist_notification(
            template_id=notification["template"],
            template_version=notification["template_version"],
            template_postage=template.postage,
            recipient=recipient,
            service=service,
            personalisation=notification["personalisation"],
            notification_type=LETTER_TYPE,
            api_key_id=notification.get("api_key", None),
            key_type=KEY_TYPE_NORMAL,
            created_at=datetime.utcnow(),
            job_id=notification["job"],
            job_row_number=notification["row_number"],
            notification_id=notification_id,
            reference=create_random_identifier(),
            reply_to_text=template.get_reply_to_text(),
            status=status,
        )

        if not service.research_mode:
            send_notification_to_queue(saved_notification, service.research_mode)
        elif current_app.config["NOTIFY_ENVIRONMENT"] in ["preview", "development"]:
            research_mode_tasks.create_fake_letter_response_file.apply_async(
                (saved_notification.reference,), queue=QueueNames.RESEARCH_MODE
            )
        else:
            update_notification_status_by_reference(saved_notification.reference, "delivered")

        current_app.logger.debug("Letter {} created at {}".format(saved_notification.id, saved_notification.created_at))
    except SQLAlchemyError as e:
        handle_exception(self, notification, notification_id, e)


@notify_celery.task(bind=True, name="update-letter-notifications-to-sent")
@statsd(namespace="tasks")
def update_letter_notifications_to_sent_to_dvla(self, notification_references):
    # This task will be called by the FTP app to update notifications as sent to DVLA
    provider = get_current_provider(LETTER_TYPE)

    updated_count, _ = dao_update_notifications_by_reference(
        notification_references,
        {
            "status": NOTIFICATION_SENDING,
            "sent_by": provider.identifier,
            "sent_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        },
    )

    current_app.logger.info("Updated {} letter notifications to sending".format(updated_count))


@notify_celery.task(bind=True, name="update-letter-notifications-to-error")
@statsd(namespace="tasks")
def update_letter_notifications_to_error(self, notification_references):
    # This task will be called by the FTP app to update notifications as sent to DVLA

    updated_count, _ = dao_update_notifications_by_reference(
        notification_references,
        {"status": NOTIFICATION_TECHNICAL_FAILURE, "updated_at": datetime.utcnow()},
    )
    message = "Updated {} letter notifications to technical-failure with references {}".format(
        updated_count, notification_references
    )
    raise NotificationTechnicalFailureException(message)


def handle_exception(task, notification, notification_id, exc):
    if not get_notification_by_id(notification_id):
        retry_msg = "{task} notification for job {job} row number {row} and notification id {noti}".format(
            task=task.__name__,
            job=notification.get("job", None),
            row=notification.get("row_number", None),
            noti=notification_id,
        )
        # Sometimes, SQS plays the same message twice. We should be able to catch an IntegrityError, but it seems
        # SQLAlchemy is throwing a FlushError. So we check if the notification id already exists then do not
        # send to the retry queue.
        current_app.logger.exception("Retry" + retry_msg)
        try:
            task.retry(queue=QueueNames.RETRY, exc=exc)
        except task.MaxRetriesExceededError:
            current_app.logger.error("Max retry failed" + retry_msg)


def handle_list_of_exception(task, list_notification, exc):
    for notification in list_notification:
        notification_id = notification.notification_id
        if not get_notification_by_id(notification_id):
            retry_msg = "{task} notification for job {job} row number {row} and notification id {noti}".format(
                task=task.__name__,
                job=notification.get("job", None),
                row=notification.get("row_number", None),
                noti=notification_id,
            )
            # Sometimes, SQS plays the same message twice. We should be able to catch an IntegrityError, but it seems
            # SQLAlchemy is throwing a FlushError. So we check if the notification id already exists then do not
            # send to the retry queue.
            current_app.logger.exception("Retry" + retry_msg)
            try:
                task.retry(queue=QueueNames.RETRY, exc=exc)
            except task.MaxRetriesExceededError:
                current_app.logger.error("Max retry failed" + retry_msg)


def get_template_class(template_type):
    if template_type == SMS_TYPE:
        return SMSMessageTemplate
    elif template_type in (EMAIL_TYPE, LETTER_TYPE):
        # since we don't need rendering capabilities (we only need to extract placeholders) both email and letter can
        # use the same base template
        return WithSubjectTemplate


@notify_celery.task(bind=True, name="update-letter-notifications-statuses")
@statsd(namespace="tasks")
def update_letter_notifications_statuses(self, filename):
    notification_updates = parse_dvla_file(filename)

    temporary_failures = []

    for update in notification_updates:
        check_billable_units(update)
        update_letter_notification(filename, temporary_failures, update)
    if temporary_failures:
        # This will alert Notify that DVLA was unable to deliver the letters, we need to investigate
        message = "DVLA response file: {filename} has failed letters with notification.reference {failures}".format(
            filename=filename, failures=temporary_failures
        )
        raise DVLAException(message)


@notify_celery.task(bind=True, name="record-daily-sorted-counts")
@statsd(namespace="tasks")
def record_daily_sorted_counts(self, filename):
    sorted_letter_counts = defaultdict(int)
    notification_updates = parse_dvla_file(filename)
    for update in notification_updates:
        sorted_letter_counts[update.cost_threshold.lower()] += 1

    unknown_status = sorted_letter_counts.keys() - {"unsorted", "sorted"}
    if unknown_status:
        message = "DVLA response file: {} contains unknown Sorted status {}".format(filename, unknown_status.__repr__())
        raise DVLAException(message)

    billing_date = get_billing_date_in_est_from_filename(filename)
    persist_daily_sorted_letter_counts(day=billing_date, file_name=filename, sorted_letter_counts=sorted_letter_counts)


def parse_dvla_file(filename):
    bucket_location = "{}-ftp".format(current_app.config["NOTIFY_EMAIL_DOMAIN"])
    response_file_content = s3.get_s3_file(bucket_location, filename)

    try:
        return process_updates_from_file(response_file_content)
    except TypeError:
        raise DVLAException("DVLA response file: {} has an invalid format".format(filename))


def get_billing_date_in_est_from_filename(filename):
    # exclude seconds from the date since we don't need it. We got a date ending in 60 second - which is not valid.
    datetime_string = filename.split("-")[1][:-2]
    datetime_obj = datetime.strptime(datetime_string, "%Y%m%d%H%M")
    return convert_utc_to_local_timezone(datetime_obj).date()


def persist_daily_sorted_letter_counts(day, file_name, sorted_letter_counts):
    daily_letter_count = DailySortedLetter(
        billing_day=day,
        file_name=file_name,
        unsorted_count=sorted_letter_counts["unsorted"],
        sorted_count=sorted_letter_counts["sorted"],
    )
    dao_create_or_update_daily_sorted_letter(daily_letter_count)


def process_updates_from_file(response_file):
    NotificationUpdate = namedtuple("NotificationUpdate", ["reference", "status", "page_count", "cost_threshold"])
    notification_updates = [NotificationUpdate(*line.split("|")) for line in response_file.splitlines()]
    return notification_updates


def update_letter_notification(filename, temporary_failures, update):
    if update.status == DVLA_RESPONSE_STATUS_SENT:
        status = NOTIFICATION_DELIVERED
    else:
        status = NOTIFICATION_TEMPORARY_FAILURE
        temporary_failures.append(update.reference)

    updated_count, _ = dao_update_notifications_by_reference(
        references=[update.reference],
        update_dict={"status": status, "updated_at": datetime.utcnow()},
    )

    if not updated_count:
        msg = (
            "Update letter notification file {filename} failed: notification either not found "
            "or already updated from delivered. Status {status} for notification reference {reference}".format(
                filename=filename, status=status, reference=update.reference
            )
        )
        current_app.logger.info(msg)


def check_billable_units(notification_update):
    notification = dao_get_notification_history_by_reference(notification_update.reference)

    if int(notification_update.page_count) != notification.billable_units:
        msg = "Notification with id {} has {} billable_units but DVLA says page count is {}".format(
            notification.id, notification.billable_units, notification_update.page_count
        )
        try:
            raise DVLAException(msg)
        except DVLAException:
            current_app.logger.exception(msg)


@notify_celery.task(bind=True, name="send-inbound-sms", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_inbound_sms_to_service(self, inbound_sms_id, service_id):
    inbound_api = get_service_inbound_api_for_service(service_id=service_id)
    if not inbound_api:
        # No API data has been set for this service
        return

    inbound_sms = dao_get_inbound_sms_by_id(service_id=service_id, inbound_id=inbound_sms_id)
    data = {
        "id": str(inbound_sms.id),
        # TODO: should we be validating and formatting the phone number here?
        "source_number": inbound_sms.user_number,
        "destination_number": inbound_sms.notify_number,
        "message": inbound_sms.content,
        "date_received": inbound_sms.provider_date.strftime(DATETIME_FORMAT),
    }

    try:
        response = request(
            method="POST",
            url=inbound_api.url,
            data=json.dumps(data),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(inbound_api.bearer_token),
            },
            timeout=60,
        )
        current_app.logger.debug(
            "send_inbound_sms_to_service sending {} to {}, response {}".format(
                inbound_sms_id, inbound_api.url, response.status_code
            )
        )
        response.raise_for_status()
    except RequestException as e:
        current_app.logger.warning(
            "send_inbound_sms_to_service failed for service_id: {} for inbound_sms_id: {} and url: {}. exc: {}".format(
                service_id, inbound_sms_id, inbound_api.url, e
            )
        )
        if not isinstance(e, HTTPError) or e.response.status_code >= 500:
            try:
                self.retry(queue=QueueNames.RETRY)
            except self.MaxRetriesExceededError:
                current_app.logger.error(
                    """Retry: send_inbound_sms_to_service has retried the max number of
                     times for service: {} and  inbound_sms {}""".format(
                        service_id, inbound_sms_id
                    )
                )


@notify_celery.task(name="process-incomplete-jobs")
@statsd(namespace="tasks")
def process_incomplete_jobs(job_ids):
    jobs = [dao_get_job_by_id(job_id) for job_id in job_ids]

    # reset the processing start time so that the check_job_status scheduled task doesn't pick this job up again
    for job in jobs:
        job.job_status = JOB_STATUS_IN_PROGRESS
        job.processing_started = datetime.utcnow()
        dao_update_job(job)

    current_app.logger.info("Resuming Job(s) {}".format(job_ids))
    for job_id in job_ids:
        process_incomplete_job(job_id)


def process_incomplete_job(job_id):
    job = dao_get_job_by_id(job_id)

    last_notification_added = dao_get_last_notification_added_for_job_id(job_id)

    if last_notification_added:
        resume_from_row = last_notification_added.job_row_number
    else:
        resume_from_row = -1  # The first row in the csv with a number is row 0

    current_app.logger.info("Resuming job {} from row {}".format(job_id, resume_from_row))

    db_template = dao_get_template_by_id(job.template_id, job.template_version)

    TemplateClass = get_template_class(db_template.template_type)
    template = TemplateClass(db_template.__dict__)

    csv = get_recipient_csv(job, template)
    for row in csv.get_rows():
        if row.index > resume_from_row:
            process_row(row, template, job, job.service)

    job_complete(job, resumed=True)


def queue_to_use(notifications_count: int) -> Optional[str]:
    """Determine which queue to use depending on given parameters.

    We only check one rule at the moment: if the CSV file is big enough,
    the notifications will be sent to the bulk queue so they don't slow down
    notifications that are transactional in nature.
    """
    large_csv_threshold = current_app.config["CSV_BULK_REDIRECT_THRESHOLD"]
    return QueueNames.BULK if notifications_count > large_csv_threshold else None


@notify_celery.task(name="process-returned-letters-list")
@statsd(namespace="tasks")
def process_returned_letters_list(notification_references):
    updated, updated_history = dao_update_notifications_by_reference(
        notification_references, {"status": NOTIFICATION_RETURNED_LETTER}
    )

    current_app.logger.info(
        "Updated {} letter notifications ({} history notifications, from {} references) to returned-letter".format(
            updated, updated_history, len(notification_references)
        )
    )


@notify_celery.task(bind=True, name="send-notify-no-reply", max_retries=5)
@statsd(namespace="tasks")
def send_notify_no_reply(self, data):
    payload = json.loads(data)

    service = dao_fetch_service_by_id(current_app.config["NOTIFY_SERVICE_ID"])
    template = dao_get_template_by_id(current_app.config["NO_REPLY_TEMPLATE_ID"])

    try:
        saved_notification = persist_notification(
            template_id=template.id,
            template_version=template.version,
            recipient=payload["sender"],
            service=service,
            personalisation={"sending_email_address": payload["recipients"][0]},
            notification_type=template.template_type,
            api_key_id=None,
            key_type=KEY_TYPE_NORMAL,
            # Ensure that the reply to is not set, if people reply
            # to these emails, they will go to the GC Notify service
            # email address, and we handle those on the SES inbound
            # Lambda
            reply_to_text=None,
        )

        send_notification_to_queue(saved_notification, False, queue=QueueNames.NOTIFY)
    except Exception:
        try:
            self.retry(queue=QueueNames.RETRY)
        except self.MaxRetriesExceededError:
            current_app.logger.error(
                f"""
                Retry: send_notify_no_reply has retried the max number of
                 times for sender {payload['sender']}"""
            )


def get_recipient_csv(job: Job, template: Template) -> RecipientCSV:
    return RecipientCSV(
        s3.get_job_from_s3(str(job.service_id), str(job.id)),
        template_type=template.template_type,
        placeholders=template.placeholders,
        max_rows=get_csv_max_rows(job.service_id),
    )
