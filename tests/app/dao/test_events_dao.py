import pytest

from sqlalchemy import func, select

from app.dao.events_dao import dao_create_event
from app.models import Event


@pytest.mark.serial
def test_create_event(notify_db_session):
    stmt = select(func.count()).select_from(Event)

    assert notify_db_session.session.scalar(stmt) == 0
    data = {'event_type': 'sucessful_login', 'data': {'something': 'random', 'in_fact': 'could be anything'}}

    event = Event(**data)
    dao_create_event(event)

    assert notify_db_session.session.scalar(stmt) == 1

    stmt = select(Event)
    event_from_db = notify_db_session.session.scalars(stmt).first()
    assert event == event_from_db

    notify_db_session.session.delete(event_from_db)
    notify_db_session.session.commit()
