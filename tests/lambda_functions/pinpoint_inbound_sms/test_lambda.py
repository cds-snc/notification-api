import json
import os
from base64 import b64decode

from lambda_functions.pinpoint_inbound_sms.pinpoint_inbound_sms_lambda import lambda_handler


def test_lambda_sends_to_queue(mocker):
    mocker.patch.dict(os.environ, {'QUEUE_PREFIX': 'some-queue-prefix-'})

    mock_queue = mocker.Mock()

    mock_sqs = mocker.Mock()
    mock_sqs.get_queue_by_name.return_value = mock_queue

    mock_boto = mocker.Mock()
    mock_boto.resource.return_value = mock_sqs

    mocker.patch('lambda_functions.pinpoint_inbound_sms.pinpoint_inbound_sms_lambda.boto3', new=mock_boto)

    event = {
        'Records': [
            {
                'EventVersion': '1.0',
                'EventSubscriptionArn': 'some_arn',
                'EventSource': 'aws:sns',
                'Sns': {
                    'SignatureVersion': '1',
                    'Timestamp': '2019-01-02T12:45:07.000Z',
                    'Signature': 'some signature',
                    'SigningCertUrl': 'some_url',
                    'MessageId': '95df01b4-ee98-5cb9-9903-4c221d41eb5e',
                    'Message': {
                        'originationNumber': '+14255550182',
                        'destinationNumber': '+12125550101',
                        'messageKeyword': 'JOIN',
                        'messageBody': 'EXAMPLE',
                        'inboundMessageId': 'cae173d2-66b9-564c-8309-21f858e9fb84',
                        'previousPublishedMessageId': 'example-id',
                    },
                    'MessageAttributes': {},
                    'Type': 'Notification',
                    'UnsubscribeUrl': 'some_url',
                    'TopicArn': 'arn:aws:sns:us-east-2:123456789012:sns-lambda',
                    'Subject': 'TestInvoke',
                },
            }
        ]
    }

    response = lambda_handler(event, mocker.Mock())
    assert response['statusCode'] == 200

    mock_sqs.get_queue_by_name.assert_called_with(QueueName='some-queue-prefix-notify-internal-tasks')

    _, kwargs = mock_queue.send_message.call_args
    sent_message_body = kwargs['MessageBody']

    envelope = json.loads(b64decode(sent_message_body))
    body = json.loads(b64decode(envelope['body']))

    assert body['task'] == 'process-pinpoint-inbound-sms'
    assert body['args'][0]['Message'] == {
        'originationNumber': '+14255550182',
        'destinationNumber': '+12125550101',
        'messageKeyword': 'JOIN',
        'messageBody': 'EXAMPLE',
        'inboundMessageId': 'cae173d2-66b9-564c-8309-21f858e9fb84',
        'previousPublishedMessageId': 'example-id',
    }
