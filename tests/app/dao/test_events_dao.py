from uuid import uuid4

from app.dao.events_dao import dao_create_event
from app.models import Event


def test_create_event(notify_db_session):
    data = {
        'id': uuid4(),
        'event_type': 'sucessful_login',
        'data': {'something': 'random', 'in_fact': 'could be anything'},
    }

    event = Event(**data)
    try:
        dao_create_event(event)

        notify_db_session.session.expire_all()
        event_from_db = notify_db_session.session.get(Event, data['id'])

        assert event_from_db is not None
    finally:
        notify_db_session.session.delete(event_from_db)
        notify_db_session.session.commit()
