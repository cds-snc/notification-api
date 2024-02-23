import pytest
from sqlalchemy import delete

from app.dao.communication_item_dao import get_communication_items
from app.models import CommunicationItem


@pytest.fixture
def db_session_with_empty_communication_items(notify_db_session):
    stmt = delete(CommunicationItem)
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()
    return notify_db_session


class TestGetCommunicationItems:
    @pytest.mark.serial
    def test_gets_all_communication_items(self, db_session_with_empty_communication_items):
        communication_item_1 = CommunicationItem(name='some name', va_profile_item_id=1)
        db_session_with_empty_communication_items.session.add(communication_item_1)

        communication_item_2 = CommunicationItem(name='some other name', va_profile_item_id=2)
        db_session_with_empty_communication_items.session.add(communication_item_2)

        retrieved_communication_items = get_communication_items()

        assert len(retrieved_communication_items) == 2
        assert communication_item_1 in retrieved_communication_items
        assert communication_item_2 in retrieved_communication_items
