import base64
import json
import os


from lambda_functions.ses_callback.ses_callback_lambda import lambda_handler


def test_lambda_handler(mocker):
    mock_queue = mocker.Mock()

    mock_sqs = mocker.Mock()
    mock_sqs.get_queue_by_name.return_value = mock_queue

    mock_boto = mocker.Mock()
    mock_boto.resource.return_value = mock_sqs

    mocker.patch('lambda_functions.ses_callback.ses_callback_lambda.boto3', new=mock_boto)

    event = {
        "Records": [
            {
                "EventVersion": "1.0",
                "EventSubscriptionArn": "some_arn",
                "EventSource": "aws:sns",
                "Sns": {
                    "SignatureVersion": "1",
                    "Timestamp": "2019-01-02T12:45:07.000Z",
                    "Signature": "some signature",
                    "SigningCertUrl": "some_url",
                    "MessageId": "95df01b4-ee98-5cb9-9903-4c221d41eb5e",
                    "Message": "Hello from SNS!",
                    "MessageAttributes": {
                        "Test": {
                            "Type": "String",
                            "Value": "TestString"
                        },
                        "TestBinary": {
                            "Type": "Binary",
                            "Value": "TestBinary"
                        }
                    },
                    "Type": "Notification",
                    "UnsubscribeUrl": "some_url",
                    "TopicArn": "arn:aws:sns:us-east-2:123456789012:sns-lambda",
                    "Subject": "TestInvoke"
                }
            }
        ]
    }

    response = lambda_handler(event, mocker.Mock())
    assert response['statusCode'] == 200

    mock_queue.send_message.assert_called_once()


def test_lambda_handler_queue_name(mocker):
    expected_queue_name = os.environ['DESTINATION_QUEUE_NAME'] = 'dev-notification-notify-internal-tasks'
    mock_queue = mocker.Mock()

    # noinspection PyPep8Naming
    def mocked_queue_name(QueueName):  # NOSONAR
        assert QueueName == expected_queue_name
        return mock_queue

    # noinspection PyPep8Naming
    def mocked_send_message(MessageBody):  # NOSONAR
        assert MessageBody
        envelope = json.loads(base64.b64decode(MessageBody))
        assert envelope['properties']['delivery_info']['routing_key'] in expected_queue_name

    mock_queue.send_message.side_effect = mocked_send_message

    mock_sqs = mocker.Mock()
    mock_sqs.get_queue_by_name.side_effect = mocked_queue_name

    mock_boto = mocker.Mock()
    mock_boto.resource.return_value = mock_sqs

    mocker.patch('lambda_functions.ses_callback.ses_callback_lambda.boto3', new=mock_boto)

    event = {
        "Records": [
            {
                "Sns": {
                    "Message": "Hello from SNS!",
                }
            }
        ]
    }

    lambda_handler(event, mocker.Mock())
