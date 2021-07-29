import json

import pytest
import requests_mock
from celery import Task
from requests import RequestException

from app.callback.webhook_callback_strategy import WebhookCallbackStrategy
from app.config import QueueNames
from app.models import ServiceCallback


@pytest.fixture
def mock_task(mocker):
    mock_task = mocker.Mock(Task)
    return mock_task


@pytest.fixture
def mock_callback(mocker):
    return mocker.Mock(ServiceCallback, url='http://some_url', bearer_token='some token')  # nosec


def test_send_callback_returns_200_if_successful(notify_api, mock_task, mock_callback):
    with requests_mock.Mocker() as request_mock:
        request_mock.post('http://some_url', json={}, status_code=200)
        WebhookCallbackStrategy.send_callback(
            task=mock_task,
            callback=mock_callback,
            payload={'message': 'hello'},
            logging_tags={'log': 'some log'}
        )

    assert request_mock.call_count == 1
    request = request_mock.request_history[0]
    assert request.url == 'http://some_url/'
    assert request.method == 'POST'
    assert request.text == json.dumps({'message': 'hello'})
    assert request.headers["Content-type"] == "application/json"
    assert request.headers["Authorization"] == "Bearer {}".format('some token')


def test_send_callback_retries_with_status_code_above_500(notify_api, mock_task, mock_callback):
    with requests_mock.Mocker() as request_mock:
        request_mock.post('http://some_url', json={}, status_code=501)
        WebhookCallbackStrategy.send_callback(
            task=mock_task,
            callback=mock_callback,
            payload={'message': 'hello'},
            logging_tags={'log': 'some log'}
        )

    mock_task.retry.assert_called_with(queue=QueueNames.RETRY)


def test_send_callback_retries_with_request_exception(notify_api, mock_task, mock_callback, mocker):
    mocker.patch("app.callback.webhook_callback_strategy.request", side_effect=RequestException())
    WebhookCallbackStrategy.send_callback(
        task=mock_task,
        callback=mock_callback,
        payload={'message': 'hello'},
        logging_tags={'log': 'some log'}
    )

    mock_task.retry.assert_called_with(queue=QueueNames.RETRY)


def test_send_callback_does_not_retry_with_status_code_404(notify_api, mock_task, mock_callback):
    with requests_mock.Mocker() as request_mock:
        request_mock.post('http://some_url', json={}, status_code=404)
        WebhookCallbackStrategy.send_callback(
            task=mock_task,
            callback=mock_callback,
            payload={'message': 'hello'},
            logging_tags={'log': 'some log'}
        )

    mock_task.retry.assert_not_called()
