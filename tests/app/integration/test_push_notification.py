import pytest
from flask import url_for
from flask_jwt_extended import create_access_token

from app.dao.permissions_dao import permission_dao
from app.feature_flags import FeatureFlag
from app.models import PLATFORM_ADMIN, Permission
from tests.app.factories.feature_flag import mock_feature_flag


@pytest.fixture
def push_notification_toggle_enabled(mocker):
    mock_feature_flag(mocker, FeatureFlag.PUSH_NOTIFICATIONS_ENABLED, 'True')


push_request_body = {'mobile_app': 'VA_FLAGSHIP_APP', 'template_id': 'some-template-id',
                     'recipient_identifier': 'some-icn', 'personalisation': None}


def test_mobile_app_push_notification_received(sample_service_push_permissions, client,
                                               push_notification_toggle_enabled):
    sample_service = sample_service_push_permissions
    user = sample_service.users[0]
    permission_dao.set_user_service_permission(
        user,
        sample_service,
        [Permission(
            service_id=sample_service.id,
            user_id=user.id,
            permission=PLATFORM_ADMIN
        )])
    user.platform_admin = True

    response = client.post(
        url_for('v2.notification.rest_push.send_push_notification', service_id=sample_service.id),
        data=push_request_body,
        headers=[('Content-Type', 'application/json'),
                 ('Authorization', f'Bearer {create_access_token(user)}')],
    ).get_data()

    assert response.result == 'success'
    assert response.status_code == 201
