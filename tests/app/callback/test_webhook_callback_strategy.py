import json
from uuid import uuid4

import pytest
import requests_mock
from requests import RequestException

from app import encryption
from app.callback.webhook_callback_strategy import WebhookCallbackStrategy, generate_callback_signature
from app.celery.exceptions import NonRetryableException, RetryableException
from app.models import ApiKey  # , ServiceCallback  TODO
from app.models import DeliveryStatusCallbackApiData


@pytest.fixture
def sample_callback_data_v3():
    return {
        'notification_id': '342d2432-6a79-4e18-afef-8c254751969b',
        'reference': 'some client reference',
        'to': '+16502532222',
        'status': 'created',
        'created_at': '2024-10-01T00:00:00.000000Z',
        'updated_at': None,
        'sent_at': None,
        'notification_type': 'sms',
        'provider': 'pinpoint',
        'status_reason': None,
        'provider_payload': None,
    }


@pytest.fixture
def sample_delivery_status_callback_api_data():
    return DeliveryStatusCallbackApiData(
        id=str(uuid4()),
        service_id=str(uuid4()),
        url='http://some_url',
        _bearer_token=encryption.encrypt('some token'),
        include_provider_payload=True,
        callback_channel='some-channel',
        callback_type='some-type',
    )


@pytest.fixture(scope='function')
def mock_statsd_client(mocker):
    return mocker.patch('app.callback.webhook_callback_strategy.statsd_client')


def test_send_callback_returns_200_if_successful(notify_api, sample_delivery_status_callback_api_data):
    with requests_mock.Mocker() as request_mock:
        request_mock.post('http://some_url', json={}, status_code=200)
        WebhookCallbackStrategy.send_callback(
            callback=sample_delivery_status_callback_api_data,
            payload={'message': 'hello'},
            logging_tags={'log': 'some log'},
        )

    assert request_mock.call_count == 1
    request = request_mock.request_history[0]
    assert request.url == 'http://some_url/'
    assert request.method == 'POST'
    assert request.text == json.dumps({'message': 'hello'})
    assert request.headers['Content-type'] == 'application/json'
    assert request.headers['Authorization'] == f'Bearer {"some token"}'


def test_send_callback_increments_statsd_client_with_success(
    notify_api, sample_delivery_status_callback_api_data, mock_statsd_client
):
    with requests_mock.Mocker() as request_mock:
        request_mock.post('http://some_url', json={}, status_code=200)
        WebhookCallbackStrategy.send_callback(
            callback=sample_delivery_status_callback_api_data,
            payload={'message': 'hello'},
            logging_tags={'log': 'some log'},
        )

    mock_statsd_client.incr.assert_called_with(
        f'callback.webhook.{sample_delivery_status_callback_api_data.callback_type}.success'
    )


def test_send_callback_raises_retryable_exception_with_status_code_above_500(
    notify_api, sample_delivery_status_callback_api_data
):
    with pytest.raises(RetryableException) as e:
        with requests_mock.Mocker() as request_mock:
            request_mock.post('http://some_url', json={}, status_code=501)
            WebhookCallbackStrategy.send_callback(
                callback=sample_delivery_status_callback_api_data,
                payload={'message': 'hello'},
                logging_tags={'log': 'some log'},
            )

    assert '501 Server Error: None for url: http://some_url/' in str(e.value)


def test_send_callback_increments_statsd_client_with_retryable_error_for_status_code_above_500(
    notify_api, sample_delivery_status_callback_api_data, mock_statsd_client
):
    with pytest.raises(RetryableException):
        with requests_mock.Mocker() as request_mock:
            request_mock.post('http://some_url', json={}, status_code=501)
            WebhookCallbackStrategy.send_callback(
                callback=sample_delivery_status_callback_api_data,
                payload={'message': 'hello'},
                logging_tags={'log': 'some log'},
            )

    mock_statsd_client.incr.assert_called_with(
        f'callback.webhook.{sample_delivery_status_callback_api_data.callback_type}.retryable_error'
    )


def test_send_callback_raises_retryable_exception_with_request_exception(
    notify_api, sample_delivery_status_callback_api_data, mocker
):
    mocker.patch('app.callback.webhook_callback_strategy.request', side_effect=RequestException())
    with pytest.raises(RetryableException):
        WebhookCallbackStrategy.send_callback(
            callback=sample_delivery_status_callback_api_data,
            payload={'message': 'hello'},
            logging_tags={'log': 'some log'},
        )


def test_send_callback_increments_statsd_client_with_retryable_error_for_request_exception(
    notify_api, sample_delivery_status_callback_api_data, mock_statsd_client, mocker
):
    mocker.patch('app.callback.webhook_callback_strategy.request', side_effect=RequestException())
    with pytest.raises(RetryableException):
        WebhookCallbackStrategy.send_callback(
            callback=sample_delivery_status_callback_api_data,
            payload={'message': 'hello'},
            logging_tags={'log': 'some log'},
        )

    mock_statsd_client.incr.assert_called_with(
        f'callback.webhook.{sample_delivery_status_callback_api_data.callback_type}.retryable_error'
    )


def test_send_callback_raises_non_retryable_exception_with_status_code_404(
    notify_api, sample_delivery_status_callback_api_data
):
    with requests_mock.Mocker() as request_mock:
        with pytest.raises(NonRetryableException) as e:
            request_mock.post('http://some_url', json={}, status_code=404)
            WebhookCallbackStrategy.send_callback(
                callback=sample_delivery_status_callback_api_data,
                payload={'message': 'hello'},
                logging_tags={'log': 'some log'},
            )

    assert '404 Client Error: None for url: http://some_url/' in str(e.value)


def test_send_callback_increments_statsd_client_with_non_retryable_error_for_status_code_404(
    notify_api, sample_delivery_status_callback_api_data, mock_statsd_client
):
    with requests_mock.Mocker() as request_mock:
        with pytest.raises(NonRetryableException):
            request_mock.post('http://some_url', json={}, status_code=404)
            WebhookCallbackStrategy.send_callback(
                callback=sample_delivery_status_callback_api_data,
                payload={'message': 'hello'},
                logging_tags={'log': 'some log'},
            )

    mock_statsd_client.incr.assert_called_with(
        f'callback.webhook.{sample_delivery_status_callback_api_data.callback_type}.non_retryable_error'
    )


def test_generate_callback_signature(
    sample_callback_data_v3,
    sample_api_key,
    mocker,
) -> None:
    mocker.patch(
        'app.callback.webhook_callback_strategy.get_unsigned_secret',
        return_value='test_generate_callback_signature',
    )
    api_key: ApiKey = sample_api_key()

    signature = generate_callback_signature(
        api_key.id,
        sample_callback_data_v3,
    )
    assert signature == '18689cf9fb9c6a9dc1e0840245d48c666d97499d3894deb0e4cf3a5ba82f3d6e'


def test_callback_signature_length(
    sample_api_key,
) -> None:
    signature = generate_callback_signature(
        sample_api_key().id,
        {'data': 'test'},
    )
    assert len(signature) == 64  # Expected length from HMAC-SHA256
