import json

import pytest
import requests_mock
from requests import RequestException

from app.callback.webhook_callback_strategy import WebhookCallbackStrategy
from app.celery.exceptions import RetryableException, NonRetryableException
from app.models import ServiceCallback


@pytest.fixture
def mock_callback(mocker):
    return mocker.Mock(ServiceCallback, url='http://some_url', bearer_token='some token')  # nosec


@pytest.fixture(scope='function')
def mock_statsd_client(mocker):
    return mocker.patch('app.callback.webhook_callback_strategy.statsd_client')


def test_send_callback_returns_200_if_successful(notify_api, mock_callback):
    with requests_mock.Mocker() as request_mock:
        request_mock.post('http://some_url', json={}, status_code=200)
        WebhookCallbackStrategy.send_callback(
            callback=mock_callback, payload={'message': 'hello'}, logging_tags={'log': 'some log'}
        )

    assert request_mock.call_count == 1
    request = request_mock.request_history[0]
    assert request.url == 'http://some_url/'
    assert request.method == 'POST'
    assert request.text == json.dumps({'message': 'hello'})
    assert request.headers['Content-type'] == 'application/json'
    assert request.headers['Authorization'] == 'Bearer {}'.format('some token')


def test_send_callback_increments_statsd_client_with_success(notify_api, mock_callback, mock_statsd_client):
    with requests_mock.Mocker() as request_mock:
        request_mock.post('http://some_url', json={}, status_code=200)
        WebhookCallbackStrategy.send_callback(
            callback=mock_callback, payload={'message': 'hello'}, logging_tags={'log': 'some log'}
        )

    mock_statsd_client.incr.assert_called_with(f'callback.webhook.{mock_callback.callback_type}.success')


def test_send_callback_raises_retryable_exception_with_status_code_above_500(notify_api, mock_callback):
    with pytest.raises(RetryableException) as e:
        with requests_mock.Mocker() as request_mock:
            request_mock.post('http://some_url', json={}, status_code=501)
            WebhookCallbackStrategy.send_callback(
                callback=mock_callback, payload={'message': 'hello'}, logging_tags={'log': 'some log'}
            )

    assert '501 Server Error: None for url: http://some_url/' in str(e.value)


def test_send_callback_increments_statsd_client_with_retryable_error_for_status_code_above_500(
    notify_api, mock_callback, mock_statsd_client
):
    with pytest.raises(RetryableException):
        with requests_mock.Mocker() as request_mock:
            request_mock.post('http://some_url', json={}, status_code=501)
            WebhookCallbackStrategy.send_callback(
                callback=mock_callback, payload={'message': 'hello'}, logging_tags={'log': 'some log'}
            )

    mock_statsd_client.incr.assert_called_with(f'callback.webhook.{mock_callback.callback_type}.retryable_error')


def test_send_callback_raises_retryable_exception_with_request_exception(notify_api, mock_callback, mocker):
    mocker.patch('app.callback.webhook_callback_strategy.request', side_effect=RequestException())
    with pytest.raises(RetryableException):
        WebhookCallbackStrategy.send_callback(
            callback=mock_callback, payload={'message': 'hello'}, logging_tags={'log': 'some log'}
        )


def test_send_callback_increments_statsd_client_with_retryable_error_for_request_exception(
    notify_api, mock_callback, mock_statsd_client, mocker
):
    mocker.patch('app.callback.webhook_callback_strategy.request', side_effect=RequestException())
    with pytest.raises(RetryableException):
        WebhookCallbackStrategy.send_callback(
            callback=mock_callback, payload={'message': 'hello'}, logging_tags={'log': 'some log'}
        )

    mock_statsd_client.incr.assert_called_with(f'callback.webhook.{mock_callback.callback_type}.retryable_error')


def test_send_callback_raises_non_retryable_exception_with_status_code_404(notify_api, mock_callback):
    with requests_mock.Mocker() as request_mock:
        with pytest.raises(NonRetryableException) as e:
            request_mock.post('http://some_url', json={}, status_code=404)
            WebhookCallbackStrategy.send_callback(
                callback=mock_callback, payload={'message': 'hello'}, logging_tags={'log': 'some log'}
            )

    assert '404 Client Error: None for url: http://some_url/' in str(e.value)


def test_send_callback_increments_statsd_client_with_non_retryable_error_for_status_code_404(
    notify_api, mock_callback, mock_statsd_client
):
    with requests_mock.Mocker() as request_mock:
        with pytest.raises(NonRetryableException):
            request_mock.post('http://some_url', json={}, status_code=404)
            WebhookCallbackStrategy.send_callback(
                callback=mock_callback, payload={'message': 'hello'}, logging_tags={'log': 'some log'}
            )

    mock_statsd_client.incr.assert_called_with(f'callback.webhook.{mock_callback.callback_type}.non_retryable_error')
