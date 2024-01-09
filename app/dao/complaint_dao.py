from datetime import timedelta

from flask import current_app
from sqlalchemy import desc, func, select

from app import db
from app.dao.dao_utils import transactional
from app.models import Complaint
from app.utils import get_local_timezone_midnight_in_utc


@transactional
def save_complaint(complaint):
    db.session.add(complaint)


def fetch_paginated_complaints(page=1):
    return Complaint.query.order_by(desc(Complaint.created_at)).paginate(
        page=page, per_page=current_app.config['PAGE_SIZE']
    )


def fetch_complaint_by_id(complaint_id):
    return db.session.scalars(select(Complaint).where(Complaint.id == complaint_id))


def fetch_complaints_by_service(service_id):
    stmt = select(Complaint).where(Complaint.service_id == service_id).order_by(desc(Complaint.created_at))
    return db.session.scalars(stmt).all()


def fetch_count_of_complaints(
    start_date,
    end_date,
):
    start_date = get_local_timezone_midnight_in_utc(start_date)
    end_date = get_local_timezone_midnight_in_utc(end_date + timedelta(days=1))

    stmt = (
        select(func.count())
        .select_from(Complaint)
        .where(Complaint.created_at >= start_date, Complaint.created_at < end_date)
    )
    return db.session.scalar(stmt)
