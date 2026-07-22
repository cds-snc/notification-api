import datetime
from typing import List

from sqlalchemy import desc

from app import db
from app.dao.dao_utils import transactional
from app.models import Report


@transactional
def create_report(report: Report) -> Report:
    """
    Add a new report entry to the database.
    Args:
        report: A Report object with the report data
    Returns:
        The created Report object
    """
    db.session.add(report)
    db.session.commit()

    return report


def get_reports_for_service(service_id: str, limit_days: int) -> List[Report]:
    """
    Get all reports for a service generated within the specified number of days.
    Args:
        service_id: The UUID of the service
        limit_days: Number of days to look back (default: 30)
    Returns:
        List of Report objects sorted by requested_at (newest first)
    """
    query = Report.query.filter_by(service_id=service_id)

    if limit_days is not None:
        date_threshold = datetime.datetime.utcnow() - datetime.timedelta(days=limit_days)
        query = query.filter(Report.requested_at >= date_threshold)

    return query.order_by(Report.requested_at.desc()).all()


def get_report_by_id(report_id) -> Report:
    return Report.query.filter_by(id=report_id).one()


def get_paginated_reports_for_service(service_id, older_than=None, page_size=10):
    filters = [Report.service_id == service_id]

    if older_than:
        older_than_requested_at = db.session.query(Report.requested_at).filter(Report.id == older_than).as_scalar()
        filters.append(Report.requested_at < older_than_requested_at)

    return Report.query.filter(*filters).order_by(desc(Report.requested_at)).paginate(per_page=page_size)


@transactional
def update_report(report: Report):
    db.session.add(report)
    db.session.commit()
