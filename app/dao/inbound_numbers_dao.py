from typing import Optional, List

from app import db
from app.dao.dao_utils import transactional
from app.service.exceptions import SmsSenderInboundNumberIntegrityException
from app.models import InboundNumber


def dao_get_inbound_numbers():
    return InboundNumber.query.order_by(InboundNumber.updated_at).all()


def dao_get_available_inbound_numbers():
    return InboundNumber.query.filter(InboundNumber.active, InboundNumber.service_id.is_(None)).all()


def dao_get_inbound_numbers_for_service(service_id: str) -> List[InboundNumber]:
    return InboundNumber.query.filter(InboundNumber.service_id == service_id).all()


def dao_get_inbound_number(inbound_number_id: str) -> Optional[InboundNumber]:
    return InboundNumber.query.filter(InboundNumber.id == inbound_number_id).first()


@transactional
def dao_set_inbound_number_active_flag(inbound_number_id: str, active: bool) -> None:
    inbound_number = InboundNumber.query.filter_by(id=inbound_number_id).first()
    inbound_number.active = active

    db.session.add(inbound_number)


@transactional
def dao_allocate_number_for_service(service_id, inbound_number_id):
    updated = InboundNumber.query.filter_by(
        id=inbound_number_id,
        active=True,
        service_id=None
    ).update(
        {"service_id": service_id}
    )
    if not updated:
        raise SmsSenderInboundNumberIntegrityException(f"Inbound number: {inbound_number_id} is not available")
    return InboundNumber.query.get(inbound_number_id)


@transactional
def dao_create_inbound_number(inbound_number: InboundNumber):
    db.session.add(inbound_number)


@transactional
def dao_update_inbound_number(inbound_number_id: str, **kwargs) -> Optional[InboundNumber]:
    inbound_number_query = InboundNumber.query.filter_by(id=inbound_number_id)
    inbound_number_query.update(kwargs)
    return inbound_number_query.one()
