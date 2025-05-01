import datetime
from typing import List

from sqlalchemy import case, func

from app import db
from app.dao.dao_utils import transactional
from app.models import Report
from app.report.utils import ReportTotals


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


def get_report_totals(service_id: str, limit_days: int) -> ReportTotals:
    """
    Get counts of reports for a service grouped by status.

    Args:
        service_id: The UUID of the service
        limit_days: Number of days to look back

    Returns:
        ReportTotals object with counts for each status category:
        - ready: count of ready reports that haven't expired
        - expired: count of ready reports that have expired
        - error: count of reports with error status
        - generating: count of reports with requested or generating status
    """

    now = datetime.datetime.utcnow()
    query = db.session.query(
        # Count ready reports that haven't expired
        func.sum(case([(Report.status == "ready", 1)], else_=0) * case([(Report.expires_at > now, 1)], else_=0)).label("ready"),
        # Count ready reports that have expired
        func.sum(case([(Report.status == "ready", 1)], else_=0) * case([(Report.expires_at <= now, 1)], else_=0)).label(
            "expired"
        ),
        # Count error reports
        func.sum(case([(Report.status == "error", 1)], else_=0)).label("error"),
        # Count generating reports (requested or generating)
        func.sum(case([(Report.status.in_(["requested", "generating"]), 1)], else_=0)).label("generating"),
    ).filter(Report.service_id == service_id)

    if limit_days is not None:
        date_threshold = now - datetime.timedelta(days=limit_days)
        query = query.filter(Report.requested_at >= date_threshold)

    result = query.first()

    return ReportTotals(
        ready=result.ready or 0,  # Handle NULL result from SQL
        expired=result.expired or 0,
        error=result.error or 0,
        generating=result.generating or 0,
    )


@transactional
def update_report(report: Report):
    db.session.add(report)
    db.session.commit()
