import uuid
from typing import List

from app import db
from app.models import CommunicationItem


def dao_create_communication_item(communication_item: CommunicationItem):
    communication_item.id = communication_item.id if communication_item.id else uuid.uuid4()
    db.session.add(communication_item)


def get_communication_items() -> List[CommunicationItem]:
    return CommunicationItem.query.all()


def get_communication_item(communication_item_id) -> CommunicationItem:
    return CommunicationItem.query.filter_by(id=communication_item_id).one()
