from app import db
from app.dao.dao_utils import transactional
from app.models import ServiceDataRetention
from sqlalchemy import select


def fetch_service_data_retention_by_id(
    service_id,
    data_retention_id,
):
    stmt = select(ServiceDataRetention).where(
        ServiceDataRetention.service_id == service_id, ServiceDataRetention.id == data_retention_id
    )
    return db.session.scalars(stmt).first()


def fetch_service_data_retention(service_id):
    stmt = (
        select(ServiceDataRetention)
        .where(ServiceDataRetention.service_id == service_id)
        .order_by(
            # in the order that models.notification_types are created (email, sms, letter)
            ServiceDataRetention.notification_type
        )
    )

    return db.session.scalars(stmt).all()


def fetch_service_data_retention_by_notification_type(
    service_id,
    notification_type,
):
    stmt = select(ServiceDataRetention).where(
        ServiceDataRetention.service_id == service_id, ServiceDataRetention.notification_type == notification_type
    )
    return db.session.scalars(stmt).first()


@transactional
def insert_service_data_retention(
    service_id,
    notification_type,
    days_of_retention,
):
    new_data_retention = ServiceDataRetention(
        service_id=service_id, notification_type=notification_type, days_of_retention=days_of_retention
    )

    db.session.add(new_data_retention)
    return new_data_retention
