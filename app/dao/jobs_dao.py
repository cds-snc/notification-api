import uuid
from datetime import datetime, timedelta
from typing import Iterable

from notifications_utils.letter_timings import (
    CANCELLABLE_JOB_LETTER_STATUSES,
    letter_can_be_cancelled,
)
from notifications_utils.statsd_decorators import statsd
from sqlalchemy import asc, desc, func

from app import db
from app.dao.dao_utils import transactional
from app.dao.date_util import get_query_date_based_on_retention_period
from app.dao.templates_dao import dao_get_template_by_id
from app.models import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FINISHED,
    JOB_STATUS_IN_PROGRESS,
    JOB_STATUS_PENDING,
    JOB_STATUS_SCHEDULED,
    LETTER_TYPE,
    NOTIFICATION_CANCELLED,
    NOTIFICATION_CREATED,
    Job,
    Notification,
    NotificationHistory,
    ServiceDataRetention,
    Template,
)


@statsd(namespace="dao")
def dao_get_notification_outcomes_for_job_batch(service_id, job_ids):
    """
    Returns a list of (job_id, status, count) tuples for the given job_ids.
    """
    return (
        db.session.query(
            Notification.job_id,
            Notification.status,
            func.count(Notification.id).label("count"),
        )
        .filter(
            Notification.service_id == service_id,
            Notification.job_id.in_(job_ids),
        )
        .group_by(Notification.job_id, Notification.status)
        .all()
    )


@statsd(namespace="dao")
def dao_get_notification_outcomes_for_job(service_id, job_id):
    notification = (
        db.session.query(func.count(Notification.status).label("count"), Notification.status)
        .filter(Notification.service_id == service_id, Notification.job_id == job_id)
        .group_by(Notification.status)
    )
    notification_history = (
        db.session.query(func.count(NotificationHistory.status).label("count"), NotificationHistory.status)
        .filter(NotificationHistory.service_id == service_id, NotificationHistory.job_id == job_id)
        .group_by(NotificationHistory.status)
    )

    return notification.union(notification_history).all()


def dao_get_job_by_service_id_and_job_id(service_id, job_id):
    return Job.query.filter_by(service_id=service_id, id=job_id).first()


def dao_get_jobs_by_service_id(service_id, limit_days=None, page=1, page_size=50, statuses=None):
    query_filter = [
        Job.service_id == service_id,
    ]
    if limit_days is not None:
        query_filter.append(Job.created_at > get_query_date_based_on_retention_period(limit_days))

    if statuses is not None and statuses != [""]:
        query_filter.append(Job.job_status.in_(statuses))
    return Job.query.filter(*query_filter).order_by(Job.created_at.desc()).paginate(page=page, per_page=page_size)


def dao_get_job_by_id(job_id) -> Job:
    return Job.query.filter_by(id=job_id).one()


def dao_archive_jobs(jobs: Iterable[Job]):
    """
    Archive the given jobs.
    Args:
        jobs (Iterable[Job]): The jobs to archive.
    """
    for job in jobs:
        job.archived = True
        db.session.add(job)
    db.session.commit()


def dao_get_in_progress_jobs():
    return Job.query.filter(Job.job_status == JOB_STATUS_IN_PROGRESS).all()


def dao_service_has_jobs(service_id):
    """
    Efficient check to see if a service has any jobs in the database.
    Returns True if the service has at least one job, False otherwise.
    """
    return db.session.query(db.session.query(Job).filter(Job.service_id == service_id).exists()).scalar()


def dao_set_scheduled_jobs_to_pending():
    """
    Sets all past scheduled jobs to pending, and then returns them for further processing.

    this is used in the run_scheduled_jobs task, so we put a FOR UPDATE lock on the job table for the duration of
    the transaction so that if the task is run more than once concurrently, one task will block the other select
    from completing until it commits.
    """
    jobs = (
        Job.query.filter(
            Job.job_status == JOB_STATUS_SCHEDULED,
            Job.scheduled_for < datetime.utcnow(),
        )
        .order_by(asc(Job.scheduled_for))
        .with_for_update()
        .all()
    )

    for job in jobs:
        job.job_status = JOB_STATUS_PENDING

    db.session.add_all(jobs)
    db.session.commit()

    return jobs


def dao_get_future_scheduled_job_by_id_and_service_id(job_id, service_id):
    return Job.query.filter(
        Job.service_id == service_id,
        Job.id == job_id,
        Job.job_status == JOB_STATUS_SCHEDULED,
        Job.scheduled_for > datetime.utcnow(),
    ).one()


def dao_create_job(job):
    if not job.id:
        job.id = uuid.uuid4()
    db.session.add(job)
    db.session.commit()


def dao_update_job(job):
    db.session.add(job)
    db.session.commit()


def dao_get_jobs_older_than_data_retention(notification_types, limit=None):
    flexible_data_retention = ServiceDataRetention.query.filter(
        ServiceDataRetention.notification_type.in_(notification_types)
    ).all()
    jobs = []
    today = datetime.utcnow().date()
    for f in flexible_data_retention:
        end_date = today - timedelta(days=f.days_of_retention)
        query = (
            Job.query.join(Template)
            .filter(
                func.coalesce(Job.scheduled_for, Job.created_at) < end_date,
                Job.archived == False,  # noqa
                Template.template_type == f.notification_type,
                Job.service_id == f.service_id,
            )
            .order_by(desc(Job.created_at))
        )
        if limit:
            query = query.limit(limit - len(jobs))
        jobs.extend(query.all())

    end_date = today - timedelta(days=7)
    for notification_type in notification_types:
        services_with_data_retention = [x.service_id for x in flexible_data_retention if x.notification_type == notification_type]
        query = (
            Job.query.join(Template)
            .filter(
                func.coalesce(Job.scheduled_for, Job.created_at) < end_date,
                Job.archived == False,  # noqa
                Template.template_type == notification_type,
                Job.service_id.notin_(services_with_data_retention),
            )
            .order_by(desc(Job.created_at))
        )
        if limit:
            query = query.limit(limit - len(jobs))
        jobs.extend(query.all())

    return jobs


@transactional
def dao_cancel_letter_job(job):
    number_of_notifications_cancelled = Notification.query.filter(Notification.job_id == job.id).update(
        {
            "status": NOTIFICATION_CANCELLED,
            "updated_at": datetime.utcnow(),
            "billable_units": 0,
        }
    )
    job.job_status = JOB_STATUS_CANCELLED
    dao_update_job(job)
    return number_of_notifications_cancelled


def can_letter_job_be_cancelled(job):
    template = dao_get_template_by_id(job.template_id)
    if template.template_type != LETTER_TYPE:
        return (
            False,
            "Only letter jobs can be cancelled through this endpoint. This is not a letter job.",
        )

    notifications = Notification.query.filter(Notification.job_id == job.id).all()
    count_notifications = len(notifications)
    if job.job_status != JOB_STATUS_FINISHED or count_notifications != job.notification_count:
        return (
            False,
            "We are still processing these letters, please try again in a minute.",
        )
    count_cancellable_notifications = len([n for n in notifications if n.status in CANCELLABLE_JOB_LETTER_STATUSES])
    if count_cancellable_notifications != job.notification_count or not letter_can_be_cancelled(
        NOTIFICATION_CREATED, job.created_at
    ):
        return (
            False,
            "It’s too late to cancel sending, these letters have already been sent.",
        )

    return True, None
