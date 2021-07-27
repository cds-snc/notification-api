import json

import pytest
import requests_mock
from celery import Task

from app.callback.webhook_callback_strategy import WebhookCallbackStrategy
from app.config import QueueNames


@pytest.fixture
def mock_task(mocker):
    mock_task = mocker.Mock(Task)
    mock_task.name = 'some task name'
    return mock_task


def test_send_callback_returns_200_if_successful(notify_api, mocker, mock_task):
    with requests_mock.Mocker() as request_mock:
        request_mock.post('http://some_url', json={}, status_code=200)
        WebhookCallbackStrategy.send_callback(  # nosec
            task=mock_task,
            payload={'message': 'hello'},
            url='http://some_url',
            logging_tags={'log': 'some log'},
            token='some token'
        )

    assert request_mock.call_count == 1
    request = request_mock.request_history[0]
    assert request.url == 'http://some_url/'
    assert request.method == 'POST'
    assert request.text == json.dumps({'message': 'hello'})
    assert request.headers["Content-type"] == "application/json"
    assert request.headers["Authorization"] == "Bearer {}".format('some token')


def test_send_callback_retries_with_status_code_above_500(notify_api, mock_task):
    with requests_mock.Mocker() as request_mock:
        request_mock.post('http://some_url', json={}, status_code=501)
        WebhookCallbackStrategy.send_callback(  # nosec
            task=mock_task,
            payload={'message': 'hello'},
            url='http://some_url',
            logging_tags={'log': 'some log'},
            token='some token'
        )

    # assert response.status_code == 501
    mock_task.retry.assert_called_with(queue=QueueNames.RETRY)
