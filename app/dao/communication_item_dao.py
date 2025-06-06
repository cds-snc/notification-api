from sqlalchemy import select

from app import db
from app.models import CommunicationItem


def get_communication_item(communication_item_id) -> CommunicationItem:
    return db.session.scalars(select(CommunicationItem).where(CommunicationItem.id == communication_item_id)).one()
