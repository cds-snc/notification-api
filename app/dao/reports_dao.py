import datetime
from typing import List

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


@transactional
def update_report(report: Report) -> Report:
    """
    Update an existing report in the database.
    Args:
        report: A Report object with updated data
    Returns:
        The updated Report object
    Raises:
        Exception: If the report with the given ID doesn't exist
    """
    existing_report = Report.query.get(report.id)
    if not existing_report:
        raise Exception(f"Report with ID {report.id} not found")

    # Update the existing report's attributes
    for key, value in report.__dict__.items():
        if key != "_sa_instance_state" and key != "id":
            setattr(existing_report, key, value)

    db.session.commit()
    return existing_report
