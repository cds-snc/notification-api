from uuid import uuid4

from flask import json

from app.models import Event
from tests import create_admin_authorization_header


def test_create_event(
    client,
    notify_db_session,
):
    data = {
        'id': str(uuid4()),
        'event_type': 'sucessful_login',
        'data': {'something': 'random', 'in_fact': 'could be anything'},
    }

    path = '/events'
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]

    response = client.post(path, data=json.dumps(data), headers=headers)

    assert response.status_code == 201
    resp_json = response.get_json()
    resp_data = resp_json['data']
    assert resp_data['event_type'] == data['event_type']
    assert resp_data['data']['something'] == data['data']['something']
    assert resp_data['data']['in_fact'] == data['data']['in_fact']

    # Teardown
    event = notify_db_session.session.get(Event, resp_data['id'])
    notify_db_session.session.delete(event)
    notify_db_session.session.commit()
