from flask import json
from tests import create_authorization_header


def test_create_event(client, notify_db_session):
    data = {'event_type': 'sucessful_login', 'data': {'something': 'random', 'in_fact': 'could be anything'}}

    path = '/events'
    auth_header = create_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]

    response = client.post(path, data=json.dumps(data), headers=headers)

    assert response.status_code == 201
    resp_json = response.get_json()['data']
    assert resp_json['event_type'] == data['event_type']
    assert resp_json['data']['something'] == data['data']['something']
    assert resp_json['data']['in_fact'] == data['data']['in_fact']
