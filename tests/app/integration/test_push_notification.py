import json
import pytest
import requests_mock
from flask import url_for
from app.feature_flags import FeatureFlag
from app.models import PUSH_TYPE
from tests.app.db import create_service
from tests.app.factories.feature_flag import mock_feature_flag
from tests import create_authorization_header


@pytest.fixture
def push_notification_toggle_enabled(mocker):
    mock_feature_flag(mocker, FeatureFlag.PUSH_NOTIFICATIONS_ENABLED, 'True')


@pytest.yield_fixture
def rmock():
    with requests_mock.mock(real_http=True) as rmock:
        yield rmock

push_request_body = {'template_id': 'some-template-id',
                     'recipient_identifier': {"id_type": "ICN", "id_value": "some-icn"},
                     'personalisation': {"%FOO%": "bar"}}


def test_mobile_app_push_notification_delivered(client, db_session, vetext_client,
                                                push_notification_toggle_enabled, rmock):
    sample_service = create_service(service_permissions=[PUSH_TYPE])
    rmock.register_uri(
        'POST',
        f"{client.application.config['VETEXT_URL']}/mobile/push/send",
        json={'result': 'success'}
    )
    # rmock.request(
    #     "POST",
    #     f"{client.application.config['VETEXT_URL']}/mobile/push/send",
    #     json={'result': 'success'}
    # )

    response = client.post(
        url_for('v2_notifications.send_push_notification', service_id=sample_service.id),
        data=json.dumps(push_request_body),
        headers=[('Content-Type', 'application/json'),
                 create_authorization_header(service_id=sample_service.id)],
    )

    print("response", response)

    assert response.result == 'success'
    assert response.status_code == 201
