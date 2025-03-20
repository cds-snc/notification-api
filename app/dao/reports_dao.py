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
