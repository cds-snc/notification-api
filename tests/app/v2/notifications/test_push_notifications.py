import pytest
import requests
import requests_mock
from celery.exceptions import CeleryError
from kombu.exceptions import OperationalError

from app.constants import PUSH_TYPE
from app.feature_flags import FeatureFlag

from tests.app.factories.feature_flag import mock_feature_flag

from . import post_send_notification


@pytest.fixture(autouse=True)
def feature_toggle_enabled(mocker):
    mock_feature_flag(mocker, feature_flag=FeatureFlag.PUSH_NOTIFICATIONS_ENABLED, enabled='True')


PUSH_REQUEST = {
    'template_id': 'some-template-id',
    'recipient_identifier': {
        'id_type': 'ICN',
        'id_value': 'some-icn',
    },
}


def push_request_without(key: str) -> dict:
    payload = PUSH_REQUEST.copy()
    del payload[key]
    return payload


class TestValidations:
    def test_checks_service_permissions(
        self,
        client,
        sample_api_key,
        sample_service,
    ):
        service = sample_service(service_permissions=[])

        response = post_send_notification(client, sample_api_key(service), PUSH_TYPE, PUSH_REQUEST)

        assert response.status_code == 403
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert 'Service is not allowed to send push notifications' in resp_json['errors'][0]['message']

    @pytest.mark.parametrize(
        'payload, error_msg',
        [
            (push_request_without('template_id'), 'template_id is a required property'),
            (push_request_without('recipient_identifier'), 'recipient_identifier is a required property'),
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

        response = post_send_notification(client, sample_api_key(service), PUSH_TYPE, payload)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert {'error': 'ValidationError', 'message': error_msg} in resp_json['errors']

    @pytest.mark.parametrize(
        'recipient_identifier, error_msg',
        [
            ({'id_type': 'ICN'}, 'recipient_identifier id_value is a required property'),
            ({'id_value': 'foo'}, 'recipient_identifier id_type is a required property'),
            ({'id_type': 'PID', 'id_value': 'foo'}, 'recipient_identifier PID is not one of [ICN]'),
        ],
    )
    def test_recipient_identifier(
        self,
        client,
        sample_api_key,
        sample_service,
        recipient_identifier,
        error_msg,
    ):
        payload = PUSH_REQUEST.copy()
        payload['recipient_identifier'] = recipient_identifier
        service = sample_service(service_permissions=[PUSH_TYPE])
        response = post_send_notification(client, sample_api_key(service), PUSH_TYPE, payload)

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

        payload = PUSH_REQUEST.copy()
        payload['mobile_app'] = 'some_mobile_app'
        response = post_send_notification(client, sample_api_key(service), PUSH_TYPE, payload)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert 'mobile_app some_mobile_app is not one of [VA_FLAGSHIP_APP]' in resp_json['errors'][0]['message']

    def test_does_not_accept_extra_fields(
        self,
        client,
        sample_api_key,
        sample_service,
    ):
        service = sample_service(service_permissions=[PUSH_TYPE])

        payload = PUSH_REQUEST.copy()
        payload['foo'] = 'bar'
        response = post_send_notification(client, sample_api_key(service), PUSH_TYPE, payload)

        assert response.status_code == 400
        assert response.headers['Content-type'] == 'application/json'
        resp_json = response.get_json()
        assert 'Additional properties are not allowed (foo was unexpected)' in resp_json['errors'][0]['message']


class TestDeliverPushCelery:
    @pytest.fixture()
    def deliver_push_celery(self, mocker):
        mocker.patch('app.v2.notifications.rest_push.deliver_push.apply_async')

    def test_returns_201(
        self,
        client,
        sample_api_key,
        sample_service,
        deliver_push_celery,
    ):
        service = sample_service(service_permissions=[PUSH_TYPE])
        response = post_send_notification(client, sample_api_key(service), PUSH_TYPE, PUSH_REQUEST)
        assert response.status_code == 201

    def test_returns_201_after_read_timeout(
        self,
        client,
        sample_api_key,
        sample_service,
        deliver_push_celery,
    ):
        with requests_mock.Mocker() as m:
            m.post(f'{client.application.config["VETEXT_URL"]}/mobile/push/send', exc=requests.exceptions.ReadTimeout)

        service = sample_service(service_permissions=[PUSH_TYPE])
        response = post_send_notification(client, sample_api_key(service), PUSH_TYPE, PUSH_REQUEST)
        assert response.status_code == 201

    @pytest.mark.parametrize('side_effect', [CeleryError, OperationalError])
    def test_celery_returns_502(self, client, sample_api_key, sample_service, mocker, side_effect):
        mocker.patch('app.v2.notifications.rest_push.deliver_push.apply_async', side_effect=side_effect)
        service = sample_service(service_permissions=[PUSH_TYPE])
        response = post_send_notification(client, sample_api_key(service), PUSH_TYPE, PUSH_REQUEST)
        assert response.status_code == 503
