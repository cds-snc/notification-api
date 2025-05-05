from sqlalchemy import desc, select

from app import db
from app.dao.dao_utils import transactional
from app.models import Complaint


@transactional
def save_complaint(complaint):
    db.session.add(complaint)


def fetch_complaint_by_id(complaint_id):
    return db.session.scalars(select(Complaint).where(Complaint.id == complaint_id))


def fetch_complaints_by_service(service_id):
    stmt = select(Complaint).where(Complaint.service_id == service_id).order_by(desc(Complaint.created_at))
    return db.session.scalars(stmt).all()
