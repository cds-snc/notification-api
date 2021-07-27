from celery import Task
from app.callback.queue_callback_strategy import QueueCallbackStrategy


def test_send_callback_enqueues_message(mocker, notify_api):
    mock_send_message = mocker.patch('app.callback.sqs_client.SQSClient.send_message')

    mock_task = mocker.Mock(Task)
    mock_task.name = 'some task name'

    QueueCallbackStrategy.send_callback(  # nosec
        task=mock_task,
        payload={'message': 'hello'},
        url='http://some_url',
        logging_tags={'log': 'some log'},
        token='some token'
    )

    mock_send_message.assert_called_with('{"message": "hello"}')
