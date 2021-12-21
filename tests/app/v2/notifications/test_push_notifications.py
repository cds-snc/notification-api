import pytest
from app.feature_flags import FeatureFlag
from app.models import PUSH_TYPE
from tests.app.factories.feature_flag import mock_feature_flag
from tests.app.db import (
    create_service,
)
from . import post_send_notification


@pytest.fixture
def service_with_push_permission(db_session):
    return create_service(service_permissions=[PUSH_TYPE])


@pytest.fixture(autouse=True)
def feature_toggle_enabled(mocker):
    mock_feature_flag(mocker, feature_flag=FeatureFlag.PUSH_NOTIFICATIONS, enabled='True')


push_request = {
    "template_id": "not important"
}


def test_returns_not_implemented_if_feature_flag_disabled(client, mocker, service_with_push_permission):
    mock_feature_flag(mocker, feature_flag=FeatureFlag.PUSH_NOTIFICATIONS, enabled='False')

    response = post_send_notification(client, service_with_push_permission, 'push', push_request)

    assert response.status_code == 501


class TestValidations:

    def test_checks_service_permissions(self, client, db_session):
        service = create_service(service_permissions=[])
        response = post_send_notification(client, service, 'push', push_request)

        assert response.status_code == 400
        resp_json = response.get_json()
        assert "Service is not allowed to send push notifications" in resp_json["errors"][0]["message"]


class TestPushSending:

    def test_returns_201(self, client, service_with_push_permission):
        response = post_send_notification(client, service_with_push_permission, 'push', push_request)

        assert response.status_code == 201
