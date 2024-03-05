"""
This module tests GET requests to /notifications endpoints.
"""

import uuid
from tests import create_authorization_header


def test_get_notification_empty_result(
    client,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())

    response = client.get(path='/notifications/{}'.format(uuid.uuid4()), headers=[auth_header])

    assert response.status_code == 404
    response_json = response.get_json()
    assert response_json['result'] == 'error'
    assert response_json['message'] == 'No result found'


def test_should_reject_invalid_page_param(
    client,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())

    response = client.get('/notifications?page=invalid', headers=[auth_header])

    assert response.status_code == 400
    response_json = response.get_json()
    assert response_json['result'] == 'error'
    assert 'Not a valid integer.' in response_json['message']['page']


def test_get_all_notifications_returns_empty_list(
    client,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())

    response = client.get('/notifications', headers=[auth_header])

    assert response.status_code == 200
    response_json = response.get_json()
    assert len(response_json['notifications']) == 0
