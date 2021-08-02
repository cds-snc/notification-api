import json

import pytest

from app.callback.queue_callback_strategy import QueueCallbackStrategy
from app.models import ServiceCallback, DELIVERY_STATUS_CALLBACK_TYPE, COMPLAINT_CALLBACK_TYPE, \
    INBOUND_SMS_CALLBACK_TYPE


@pytest.mark.parametrize("callback_type",
                         [DELIVERY_STATUS_CALLBACK_TYPE, COMPLAINT_CALLBACK_TYPE, INBOUND_SMS_CALLBACK_TYPE])
def test_send_callback_enqueues_message(mocker, notify_api, callback_type):
    mock_send_message = mocker.patch('app.callback.sqs_client.SQSClient.send_message')

    mock_callback = mocker.Mock(  # nosec
        ServiceCallback,
        url='http://some_url',
        bearer_token='some token',
        callback_type=callback_type
    )

    QueueCallbackStrategy.send_callback(
        callback=mock_callback,
        payload={'message': 'hello'},
        logging_tags={'log': 'some log'},
    )

    _, kwargs = mock_send_message.call_args
    assert kwargs['url'] == 'http://some_url'
    assert kwargs['payload'] == json.dumps({"message": "hello"})
    assert kwargs['message_attributes'] == {
        "callback_type": {"DataType": "String", "StringValue": mock_callback.callback_type}
    }
