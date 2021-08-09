from typing import List

from app.models import CommunicationItem


def get_communication_items() -> List[CommunicationItem]:
    return CommunicationItem.query.all()
