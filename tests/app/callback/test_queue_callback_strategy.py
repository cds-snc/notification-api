import pytest
from botocore.exceptions import ClientError

from app.callback.queue_callback_strategy import QueueCallbackStrategy
from app.celery.exceptions import NonRetryableException
from app.models import (
    ServiceCallback,
    DELIVERY_STATUS_CALLBACK_TYPE,
    COMPLAINT_CALLBACK_TYPE,
    INBOUND_SMS_CALLBACK_TYPE,
)


@pytest.fixture(scope='function')
def mock_statsd_client(mocker):
    return mocker.patch('app.callback.queue_callback_strategy.statsd_client')


@pytest.mark.parametrize(
    'callback_type', [DELIVERY_STATUS_CALLBACK_TYPE, COMPLAINT_CALLBACK_TYPE, INBOUND_SMS_CALLBACK_TYPE]
)
def test_send_callback_enqueues_message(mocker, notify_api, callback_type):
    mock_send_message = mocker.patch('app.callback.sqs_client.SQSClient.send_message')

    mock_callback = mocker.Mock(  # nosec
        ServiceCallback, url='http://some_url', bearer_token='some token', callback_type=callback_type
    )

    QueueCallbackStrategy.send_callback(
        callback=mock_callback,
        payload={'message': 'hello'},
        logging_tags={'log': 'some log'},
    )

    _, kwargs = mock_send_message.call_args
    assert kwargs['url'] == 'http://some_url'
    assert kwargs['message_body'] == {'message': 'hello'}
    assert kwargs['message_attributes'] == {
        'CallbackType': {'DataType': 'String', 'StringValue': mock_callback.callback_type},
    }


def test_send_callback_increments_statsd_client_with_success(client, mocker, mock_statsd_client):
    mocker.patch('app.callback.sqs_client.SQSClient.send_message')

    mock_callback = mocker.Mock(  # nosec
        ServiceCallback, url='http://some_url', bearer_token='some token', callback_type=DELIVERY_STATUS_CALLBACK_TYPE
    )

    QueueCallbackStrategy.send_callback(
        callback=mock_callback,
        payload={'message': 'hello'},
        logging_tags={'log': 'some log'},
    )

    mock_statsd_client.incr.assert_called_with(f'callback.queue.{DELIVERY_STATUS_CALLBACK_TYPE}.success')


def test_send_callback_raises_non_retryable_exception_on_client_error(mocker, notify_api):
    mock_send_message = mocker.patch('app.callback.sqs_client.SQSClient.send_message')
    mock_send_message.side_effect = ClientError(
        error_response={'Error': {'Message': 'foo', 'Code': 'bar'}}, operation_name='some_operation_name'
    )

    mock_callback = mocker.Mock(  # nosec
        ServiceCallback, url='http://some_url', bearer_token='some token', callback_type=DELIVERY_STATUS_CALLBACK_TYPE
    )

    with pytest.raises(NonRetryableException):
        QueueCallbackStrategy.send_callback(
            callback=mock_callback,
            payload={'message': 'hello'},
            logging_tags={'log': 'some log'},
        )


def test_send_callback_increments_statsd_client_with_non_retryable_error(client, mocker, mock_statsd_client):
    mock_send_message = mocker.patch('app.callback.sqs_client.SQSClient.send_message')
    mock_send_message.side_effect = ClientError(
        error_response={'Error': {'Message': 'foo', 'Code': 'bar'}}, operation_name='some_operation_name'
    )

    mock_callback = mocker.Mock(  # nosec
        ServiceCallback, url='http://some_url', bearer_token='some token', callback_type=DELIVERY_STATUS_CALLBACK_TYPE
    )

    with pytest.raises(NonRetryableException):
        QueueCallbackStrategy.send_callback(
            callback=mock_callback,
            payload={'message': 'hello'},
            logging_tags={'log': 'some log'},
        )

    mock_statsd_client.incr.assert_called_with(f'callback.queue.{DELIVERY_STATUS_CALLBACK_TYPE}.non_retryable_error')
