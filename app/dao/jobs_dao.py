import uuid
from datetime import datetime, timedelta

from sqlalchemy import (
    asc,
    desc,
    func,
    select,
)

from app import db
from app.constants import (
    JOB_STATUS_PENDING,
    JOB_STATUS_SCHEDULED,
)

from app.models import (
    Job,
    Template,
    ServiceDataRetention,
)


def dao_get_job_by_id(job_id):
    return db.session.scalars(select(Job).where(Job.id == job_id)).one()


def dao_archive_job(job):
    job.archived = True
    db.session.add(job)
    db.session.commit()


def dao_set_scheduled_jobs_to_pending():
    """
    Sets all past scheduled jobs to pending, and then returns them for further processing.

    this is used in the run_scheduled_jobs task, so we put a FOR UPDATE lock on the job table for the duration of
    the transaction so that if the task is run more than once concurrently, one task will block the other select
    from completing until it commits.
    """

    stmt = (
        select(Job)
        .where(Job.job_status == JOB_STATUS_SCHEDULED, Job.scheduled_for < datetime.utcnow())
        .order_by(asc(Job.scheduled_for))
        .with_for_update()
    )

    jobs = db.session.scalars(stmt).all()

    for job in jobs:
        job.job_status = JOB_STATUS_PENDING

    db.session.add_all(jobs)
    db.session.commit()

    return jobs


def dao_create_job(job):
    if not job.id:
        job.id = uuid.uuid4()
    db.session.add(job)
    db.session.commit()


def dao_update_job(job):
    db.session.add(job)
    db.session.commit()


def dao_get_jobs_older_than_data_retention(notification_types):
    stmt = select(ServiceDataRetention).where(ServiceDataRetention.notification_type.in_(notification_types))
    flexible_data_retention = db.session.scalars(stmt).all()

    jobs = []
    today = datetime.utcnow().date()
    for f in flexible_data_retention:
        end_date = today - timedelta(days=f.days_of_retention)

        stmt = (
            select(Job)
            .join(Template)
            .where(
                func.coalesce(Job.scheduled_for, Job.created_at) < end_date,
                Job.archived.is_(False),
                Template.template_type == f.notification_type,
                Job.service_id == f.service_id,
            )
            .order_by(desc(Job.created_at))
        )

        jobs.extend(db.session.scalars(stmt).all())

    end_date = today - timedelta(days=7)
    for notification_type in notification_types:
        services_with_data_retention = [
            x.service_id for x in flexible_data_retention if x.notification_type == notification_type
        ]

        stmt = (
            select(Job)
            .join(Template)
            .where(
                func.coalesce(Job.scheduled_for, Job.created_at) < end_date,
                Job.archived.is_(False),
                Template.template_type == notification_type,
                Job.service_id.notin_(services_with_data_retention),
            )
            .order_by(desc(Job.created_at))
        )

        jobs.extend(db.session.scalars(stmt).all())

    return jobs
