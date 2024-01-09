from app import db
from app.models import Event


def dao_create_event(event):
    """
    Given a dictionary of event data like . . .

    {'event_type': 'sucessful_login', 'data': {'in_fact': 'could be anything', 'something': 'random'}}

    . . . persist a new Event instance.
    """

    if isinstance(event, dict):
        event_instance = Event(**event)
    elif isinstance(event, Event):
        event_instance = event
    else:
        raise TypeError(f'Event is of type {type(event)}.')

    db.session.add(event_instance)
    db.session.commit()
