from app import db
from app.dao.dao_utils import transactional
from app.models import InboundNumber
from sqlalchemy import select, update
from typing import Optional, List


def dao_get_inbound_numbers() -> List[InboundNumber]:
    stmt = select(InboundNumber).order_by(InboundNumber.updated_at)
    return db.session.scalars(stmt).all()


def dao_get_available_inbound_numbers() -> List[InboundNumber]:
    stmt = select(InboundNumber).where(InboundNumber.active, InboundNumber.service_id.is_(None))
    return db.session.scalars(stmt).all()


def dao_get_inbound_numbers_for_service(service_id: str) -> List[InboundNumber]:
    return db.session.scalars(select(InboundNumber).where(InboundNumber.service_id == service_id)).all()


@transactional
def dao_set_inbound_number_active_flag(
    inbound_number_id: str,
    active: bool,
) -> None:
    inbound_number = db.session.get(InboundNumber, inbound_number_id)
    inbound_number.active = active

    db.session.add(inbound_number)


@transactional
def dao_create_inbound_number(inbound_number: InboundNumber):
    db.session.add(inbound_number)


@transactional
def dao_update_inbound_number(
    inbound_number_id: str,
    **kwargs,
) -> Optional[InboundNumber]:
    stmt = update(InboundNumber).where(InboundNumber.id == inbound_number_id).values(**kwargs)

    db.session.execute(stmt)
    db.session.commit()

    return db.session.scalars(select(InboundNumber).where(InboundNumber.id == inbound_number_id)).one()
