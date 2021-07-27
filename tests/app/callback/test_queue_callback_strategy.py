from celery import Task
from app.callback.queue_callback_strategy import QueueCallbackStrategy
from app.models import ServiceCallback


def test_send_callback_enqueues_message(mocker, notify_api):
    mock_send_message = mocker.patch('app.callback.sqs_client.SQSClient.send_message')

    mock_callback = mocker.Mock(ServiceCallback, url='http://some_url', bearer_token='some token')  # nosec

    QueueCallbackStrategy.send_callback(
        task=mocker.Mock(Task),
        callback=mock_callback,
        payload={'message': 'hello'},
        logging_tags={'log': 'some log'},
    )

    mock_send_message.assert_called_with('{"message": "hello"}')
