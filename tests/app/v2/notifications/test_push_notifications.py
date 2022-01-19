import pytest
import os
from app.feature_flags import FeatureFlag
from app.models import PUSH_TYPE
from app.mobile_app import MobileAppType, DEAFULT_MOBILE_APP_TYPE
from app.va.vetext import VETextClient, VETextBadRequestException, VETextNonRetryableException, VETextRetryableException
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
    mock_feature_flag(mocker, feature_flag=FeatureFlag.PUSH_NOTIFICATIONS_ENABLED, enabled='True')


push_request = {
    "template_id": "some-template-id",
    "recipient_identifier": {"id_type": "ICN", "id_value": "some-icn"}
}


def push_request_without(key: str) -> dict:
    payload = {**push_request}
    payload.pop(key)
    return payload


def test_returns_not_implemented_if_feature_flag_disabled(client, mocker, service_with_push_permission):
    mock_feature_flag(mocker, feature_flag=FeatureFlag.PUSH_NOTIFICATIONS_ENABLED, enabled='False')

    response = post_send_notification(client, service_with_push_permission, 'push', push_request)

    assert response.status_code == 501


class TestValidations:

    def test_checks_service_permissions(self, client, db_session):
        service = create_service(service_permissions=[])
        response = post_send_notification(client, service, 'push', push_request)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert "Service is not allowed to send push notifications" in resp_json["errors"][0]["message"]

    @pytest.mark.parametrize("payload, error_msg", [
        (push_request_without('template_id'), "template_id is a required property"),
        (push_request_without('recipient_identifier'), "recipient_identifier is a required property"),
    ])
    def test_required_fields(self, client, service_with_push_permission, payload, error_msg):
        response = post_send_notification(client, service_with_push_permission, 'push', payload)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert {
            'error': 'ValidationError',
            'message': error_msg
        } in resp_json['errors']

    @pytest.mark.parametrize("recipient_identifier, error_msg", [
        ({"id_type": "ICN"}, "recipient_identifier id_value is a required property"),
        ({"id_value": "foo"}, "recipient_identifier id_type is a required property"),
        ({"id_type": "PID", "id_value": 'foo'}, "recipient_identifier PID is not one of [ICN]"),
    ])
    def test_recipient_identifier(self, client, service_with_push_permission, recipient_identifier, error_msg):
        payload = {**push_request}
        payload["recipient_identifier"] = recipient_identifier
        response = post_send_notification(client, service_with_push_permission, 'push', payload)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert {
            'error': 'ValidationError',
            'message': error_msg
        } in resp_json['errors']

    def test_accepts_only_mobile_app_enum(self, client, service_with_push_permission):
        payload = {**push_request}
        payload["mobile_app"] = "some_mobile_app"

        response = post_send_notification(client, service_with_push_permission, 'push', payload)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert "mobile_app some_mobile_app is not one of [VA_FLAGSHIP_APP, VETEXT]" in resp_json["errors"][0]["message"]

    def test_does_not_accept_extra_fields(self, client, service_with_push_permission):
        payload = {**push_request}
        payload["foo"] = "bar"

        response = post_send_notification(client, service_with_push_permission, 'push', payload)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert "Additional properties are not allowed (foo was unexpected)" in resp_json["errors"][0]["message"]


class TestPushSending:
    @pytest.fixture(autouse=True)
    def mobile_app_sids(self, mocker, request):
        if 'disable_autouse' in request.keywords:
            for app in MobileAppType.values():
                mocker.patch.dict(os.environ, {f'{app}_SID': f''})
            yield
        else:
            for app in MobileAppType.values():
                mocker.patch.dict(os.environ, {f'{app}_SID': f'some_sid_for_{app}'})
            yield

    @pytest.fixture()
    def vetext_client(self, mocker):
        client = mocker.Mock(spec=VETextClient)
        mocker.patch('app.v2.notifications.rest_push.vetext_client', client)
        return client

    def test_returns_201(self, client, service_with_push_permission, vetext_client):
        response = post_send_notification(client, service_with_push_permission, 'push', push_request)

        assert response.status_code == 201

    @pytest.mark.parametrize('payload, personalisation, app', [
`        (push_request, None, DEAFULT_MOBILE_APP_TYPE.value),
`        ({**push_request, 'personalisation': {'foo': 'bar'},
            'mobile_app': MobileAppType.VETEXT.value}, {'foo': 'bar'},
            MobileAppType.VETEXT.value)
    ])
    def test_makes_call_to_vetext_client(self, client, service_with_push_permission, vetext_client,
                                         payload, personalisation, app):
        post_send_notification(client, service_with_push_permission, 'push', payload)

        vetext_client.send_push_notification.assert_called_once_with(
            f'some_sid_for_{app}',
            payload['template_id'],
            payload['recipient_identifier']['id_value'],
            personalisation
        )

    @pytest.mark.parametrize('exception', [
        VETextRetryableException,
        VETextNonRetryableException
    ])
    def test_returns_502_on_exception_other_than_bad_request(self, client, service_with_push_permission, vetext_client,
                                                             exception):
        vetext_client.send_push_notification.side_effect = exception
        response = post_send_notification(client, service_with_push_permission, 'push', push_request)

        assert response.status_code == 502
        resp_json = response.get_json()
        assert resp_json['result'] == 'error'
        assert resp_json['message'] == 'Invalid response from downstream service'

    @pytest.mark.parametrize('exception', [
        VETextBadRequestException(message='Invalid Application SID'),
        VETextBadRequestException(message='Invalid Template SID'),
    ])
    def test_maps_bad_request_exception(self, client, service_with_push_permission, vetext_client,
                                        exception):
        vetext_client.send_push_notification.side_effect = exception
        response = post_send_notification(client, service_with_push_permission, 'push', push_request)

        assert response.status_code == 400
        resp_json = response.get_json()
        assert {
            'error': 'BadRequestError',
            'message': exception.message
        } in resp_json['errors']

    @pytest.mark.disable_autouse
    def test_returns_503_if_mobile_app_not_initiliazed(self, client, service_with_push_permission):
        response = post_send_notification(client, service_with_push_permission, 'push', push_request)

        assert response.status_code == 503
        resp_json = response.get_json()
        assert resp_json == {
            'result': 'error',
            'message': 'Mobile app is not initialized'
        }
