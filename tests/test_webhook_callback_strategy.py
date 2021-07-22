import requests_mock
from celery import Task
from flask import Response

from app.callback.webhook_callback_strategy import WebhookCallbackStrategy


def test_send_callback_returns_200_if_successful(notify_api, mocker):
    mocker.Mock(
        Response, status_code=200
    )

    mock_task = mocker.Mock(Task)
    mock_task.name = 'some task name'

    with requests_mock.Mocker() as request_mock:
        request_mock.post('http://some_url', json={}, status_code=200)
        response = WebhookCallbackStrategy.send_callback(
            task=mock_task,
            payload={'message': 'hello'},
            url='http://some_url',
            logging_tags={'log': 'some log'},
            token='some token'
        )

    assert response.status_code == 200
