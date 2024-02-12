import pytest
import os
import requests
import requests_mock
from . import post_send_push_broadcast_notification
from app.va.vetext import (
    VETextClient,
    VETextBadRequestException,
    VETextNonRetryableException,
    VETextRetryableException,
)
from app.feature_flags import FeatureFlag
from app.mobile_app import MobileAppType, DEAFULT_MOBILE_APP_TYPE
from app.models import PUSH_TYPE
from tests.app.factories.feature_flag import mock_feature_flag


@pytest.fixture(autouse=True)
def feature_toggle_enabled(mocker):
    mock_feature_flag(mocker, feature_flag=FeatureFlag.PUSH_NOTIFICATIONS_ENABLED, enabled='True')


PUSH_BROADCAST_REQUEST = {
    'template_id': 'some-template-id',
    'topic_sid': 'some-topic-sid',
}


def push_broadcast_request_without(key: str) -> dict:
    payload = PUSH_BROADCAST_REQUEST.copy()
    del payload[key]
    return payload


def test_returns_not_implemented_if_feature_flag_disabled(
    client,
    mocker,
    sample_api_key,
    sample_service,
):
    mock_feature_flag(mocker, feature_flag=FeatureFlag.PUSH_NOTIFICATIONS_ENABLED, enabled='False')
    service = sample_service(service_permissions=[PUSH_TYPE])
    response = post_send_push_broadcast_notification(client, sample_api_key(service), PUSH_BROADCAST_REQUEST)
    assert response.status_code == 501


class TestValidations:
    def test_checks_service_permissions(
        self,
        client,
        sample_api_key,
        sample_service,
    ):
        service = sample_service(service_permissions=[])

        response = post_send_push_broadcast_notification(client, sample_api_key(service), PUSH_BROADCAST_REQUEST)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert 'Service is not allowed to send push notifications' in resp_json['errors'][0]['message']

    @pytest.mark.parametrize(
        'payload, error_msg',
        [
            (push_broadcast_request_without('template_id'), 'template_id is a required property'),
            (push_broadcast_request_without('topic_sid'), 'topic_sid is a required property'),
        ],
    )
    def test_required_fields(
        self,
        client,
        sample_api_key,
        sample_service,
        payload,
        error_msg,
    ):
        service = sample_service(service_permissions=[PUSH_TYPE])

        response = post_send_push_broadcast_notification(client, sample_api_key(service), payload)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert {'error': 'ValidationError', 'message': error_msg} in resp_json['errors']

    def test_accepts_only_mobile_app_enum(
        self,
        client,
        sample_api_key,
        sample_service,
    ):
        service = sample_service(service_permissions=[PUSH_TYPE])

        payload = PUSH_BROADCAST_REQUEST.copy()
        payload['mobile_app'] = 'some_mobile_app'
        response = post_send_push_broadcast_notification(client, sample_api_key(service), payload)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert 'mobile_app some_mobile_app is not one of [VA_FLAGSHIP_APP, VETEXT]' in resp_json['errors'][0]['message']

    def test_does_not_accept_extra_fields(
        self,
        client,
        sample_api_key,
        sample_service,
    ):
        service = sample_service(service_permissions=[PUSH_TYPE])

        payload = PUSH_BROADCAST_REQUEST.copy()
        payload['foo'] = 'bar'
        response = post_send_push_broadcast_notification(client, sample_api_key(service), payload)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert 'Additional properties are not allowed (foo was unexpected)' in resp_json['errors'][0]['message']


class TestPushSending:
    @pytest.fixture(autouse=True)
    def mobile_app_sids(self, mocker, request):
        if 'disable_autouse' in request.keywords:
            for app in MobileAppType.values():
                mocker.patch.dict(os.environ, {f'{app}_SID': ''})
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

    def test_returns_201(
        self,
        client,
        sample_api_key,
        sample_service,
        vetext_client,
    ):
        service = sample_service(service_permissions=[PUSH_TYPE])
        response = post_send_push_broadcast_notification(client, sample_api_key(service), PUSH_BROADCAST_REQUEST)
        assert response.status_code == 201

    def test_returns_201_after_read_timeout(
        self,
        client,
        sample_api_key,
        sample_service,
        vetext_client,
    ):
        with requests_mock.Mocker() as m:
            m.post(f'{client.application.config["VETEXT_URL"]}/mobile/push/send', exc=requests.exceptions.ReadTimeout)

        service = sample_service(service_permissions=[PUSH_TYPE])
        response = post_send_push_broadcast_notification(client, sample_api_key(service), PUSH_BROADCAST_REQUEST)
        assert response.status_code == 201

    @pytest.mark.parametrize(
        'payload, personalisation, app',
        [
            (PUSH_BROADCAST_REQUEST, None, DEAFULT_MOBILE_APP_TYPE.value),
            (
                {**PUSH_BROADCAST_REQUEST, 'personalisation': {'foo': 'bar'}, 'mobile_app': MobileAppType.VETEXT.value},
                {'foo': 'bar'},
                MobileAppType.VETEXT.value,
            ),
        ],
    )
    def test_makes_call_to_vetext_client(
        self,
        client,
        sample_api_key,
        sample_service,
        vetext_client,
        payload,
        personalisation,
        app,
    ):
        service = sample_service(service_permissions=[PUSH_TYPE])

        post_send_push_broadcast_notification(client, sample_api_key(service), payload)
        vetext_client.send_push_notification.assert_called_once_with(
            f'some_sid_for_{app}', payload['template_id'], payload['topic_sid'], True, personalisation
        )

    @pytest.mark.parametrize('exception', [VETextRetryableException, VETextNonRetryableException])
    def test_returns_502_on_exception_other_than_bad_request(
        self,
        client,
        sample_api_key,
        sample_service,
        vetext_client,
        exception,
    ):
        vetext_client.send_push_notification.side_effect = exception
        service = sample_service(service_permissions=[PUSH_TYPE])

        response = post_send_push_broadcast_notification(client, sample_api_key(service), PUSH_BROADCAST_REQUEST)

        assert response.status_code == 502
        resp_json = response.get_json()
        assert resp_json['result'] == 'error'
        assert resp_json['message'] == 'Invalid response from downstream service'

    @pytest.mark.parametrize(
        'exception',
        [
            VETextBadRequestException(message='Invalid Application SID'),
            VETextBadRequestException(message='Invalid Template SID'),
        ],
    )
    def test_maps_bad_request_exception(
        self,
        client,
        sample_api_key,
        sample_service,
        vetext_client,
        exception,
    ):
        vetext_client.send_push_notification.side_effect = exception
        service = sample_service(service_permissions=[PUSH_TYPE])

        response = post_send_push_broadcast_notification(client, sample_api_key(service), PUSH_BROADCAST_REQUEST)

        assert response.status_code == 400
        resp_json = response.get_json()
        assert {'error': 'BadRequestError', 'message': exception.message} in resp_json['errors']

    @pytest.mark.disable_autouse
    def test_returns_503_if_mobile_app_not_initiliazed(
        self,
        client,
        sample_api_key,
        sample_service,
    ):
        service = sample_service(service_permissions=[PUSH_TYPE])

        response = post_send_push_broadcast_notification(client, sample_api_key(service), PUSH_BROADCAST_REQUEST)

        assert response.status_code == 503
        resp_json = response.get_json()
        assert resp_json == {'result': 'error', 'message': 'Mobile app is not initialized'}
