from uuid import uuid4

import pytest
from sqlalchemy.orm.exc import NoResultFound

from app.dao.communication_item_dao import get_communication_item


def test_get_communication_item(sample_communication_item):
    communication_item = sample_communication_item()
    communication_item_from_dao = get_communication_item(str(communication_item.id))
    assert communication_item.id == communication_item_from_dao.id


def test_get_communication_item_not_found():
    with pytest.raises(NoResultFound):
        get_communication_item(str(uuid4()))
