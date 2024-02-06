import json
import os
import pytest
from flask import url_for
from app.feature_flags import FeatureFlag
from app.models import PUSH_TYPE
from tests.app.factories.feature_flag import mock_feature_flag
from tests import create_authorization_header


@pytest.fixture
def push_notification_toggle_enabled(mocker):
    mock_feature_flag(mocker, FeatureFlag.PUSH_NOTIFICATIONS_ENABLED, 'True')


def test_mobile_app_push_notification_delivered(
    client,
    push_notification_toggle_enabled,
    rmock,
    mocker,
    sample_api_key,
    sample_service,
):
    service = sample_service(service_permissions=[PUSH_TYPE])
    api_key = sample_api_key(service=service)
    rmock.register_uri(
        'POST', f"{client.application.config['VETEXT_URL']}/mobile/push/send", json={'result': 'success'}
    )

    push_request_body = {
        'mobile_app': 'VETEXT',
        'template_id': 'some-template-id',
        'recipient_identifier': {'id_type': 'ICN', 'id_value': 'some-icn'},
        'personalisation': {'%FOO%': 'bar'},
    }

    mocker.patch.dict(os.environ, {'VETEXT_SID': '1234', 'VA_FLAGSHIP_APP_SID': '1234'})

    response = client.post(
        url_for('v2_notifications.send_push_notification', service_id=service.id),
        data=json.dumps(push_request_body),
        headers=[
            ('Content-Type', 'application/json'),
            create_authorization_header(api_key),
        ],
    )

    assert rmock.called
    assert response.json.get('result') == 'success'
    assert response.status_code == 201
