from marshmallow import ValidationError
from sqlalchemy.orm.exc import NoResultFound

from app.dao.communication_item_dao import get_communication_item


def validate_communication_item_id(request: dict):
    communication_item_id = request.get('communication_item_id')

    if communication_item_id is not None:
        try:
            get_communication_item(communication_item_id)
        except NoResultFound:
            raise ValidationError(f'Invalid communication item id: {communication_item_id}')
