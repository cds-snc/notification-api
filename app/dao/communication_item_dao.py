from typing import List

from app.models import CommunicationItem


def get_communication_items() -> List[CommunicationItem]:
    return CommunicationItem.query.all()


def get_communication_item(communication_item_id) -> CommunicationItem:
    return CommunicationItem.query.filter_by(id=communication_item_id).one()
