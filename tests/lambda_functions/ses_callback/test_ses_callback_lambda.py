import base64
import json
import os


from lambda_functions.ses_callback.ses_callback_lambda import lambda_handler, ROUTING_KEY

CALLBACK_LAMBDA_BOTO = 'lambda_functions.ses_callback.ses_callback_lambda.boto3'


def test_lambda_handler(mocker):
    mock_queue = mocker.Mock()

    mock_sqs = mocker.Mock()
    mock_sqs.get_queue_by_name.return_value = mock_queue

    mock_boto = mocker.Mock()
    mock_boto.resource.return_value = mock_sqs

    mocker.patch(CALLBACK_LAMBDA_BOTO, new=mock_boto)

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
                    'Message': 'Hello from SNS!',
                    'MessageAttributes': {
                        'Test': {'Type': 'String', 'Value': 'TestString'},
                        'TestBinary': {'Type': 'Binary', 'Value': 'TestBinary'},
                    },
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

    mock_queue.send_message.assert_called_once()


def test_lambda_handler_queue_name(mocker):
    queue_name_prefix = os.environ['NOTIFICATION_QUEUE_PREFIX'] = 'test-notification-'
    expected_queue_name = f'{queue_name_prefix}{ROUTING_KEY}'
    mock_queue = mocker.Mock()

    # noinspection PyPep8Naming
    def mocked_queue_name(QueueName):  # NOSONAR
        assert QueueName == expected_queue_name
        return mock_queue

    # noinspection PyPep8Naming
    def mocked_send_message(MessageBody):  # NOSONAR
        assert MessageBody
        envelope = json.loads(base64.b64decode(MessageBody))
        assert envelope['properties']['delivery_info']['routing_key'] == ROUTING_KEY

    mock_queue.send_message.side_effect = mocked_send_message

    mock_sqs = mocker.Mock()
    mock_sqs.get_queue_by_name.side_effect = mocked_queue_name

    mock_boto = mocker.Mock()
    mock_boto.resource.return_value = mock_sqs

    mocker.patch(CALLBACK_LAMBDA_BOTO, new=mock_boto)

    event = {
        'Records': [
            {
                'Sns': {
                    'Message': 'Hello from SNS!',
                }
            }
        ]
    }

    lambda_handler(event, mocker.Mock())


def test_lambda_handler_queue_name_with_message(mocker):
    queue_name_prefix = os.environ['NOTIFICATION_QUEUE_PREFIX'] = 'test-notification-'
    expected_queue_name = f'{queue_name_prefix}{ROUTING_KEY}'
    mock_queue = mocker.Mock()

    some_recipient = 'somebody@some.organization.com'
    some_source_email = 'test@notifications.va.gov'
    event = {
        'Records': [
            {
                'Sns': {
                    'Message': {
                        'delivery': {
                            'timestamp': '2021-01-27T21:10:19.584Z',
                            'processingTimeMillis': 3409,
                            'recipients': [some_recipient],
                            'smtpResponse': '250 2.0.0 OK  1611781819 b3si3790733pgk.485 - gsmtp',
                            'reportingMTA': 'd210-3.smtp-out.us-us-east-1.amazonses.com',
                        },
                        'mail': {
                            'timestamp': '2021-01-27T21:10:16.175Z',
                            'source': some_source_email,
                            'sourceArn': 'arn:aws-us-gov:ses:us-gov-west-1:171875617347:identity/notifications.va.gov',
                            'sendingAccountId': '171875617347',
                            'messageId': '010a017745aebf6f-aaddaeab-8091-4930-8c9e-34279e23950c-000000',
                            'destination': [some_recipient],
                            'headersTruncated': False,
                            'headers': [
                                {'name': 'From', 'value': some_source_email},
                                {'name': 'To', 'value': some_recipient},
                                {'name': 'Subject', 'value': 'test2'},
                                {'name': 'MIME-Version', 'value': '1.0'},
                                {'name': 'Content-Type', 'value': 'text/plain; charset=UTF-8'},
                                {'name': 'Content-Transfer-Encoding', 'value': '7bit'},
                            ],
                            'commonHeaders': {
                                'from': [some_source_email],
                                'to': [some_recipient],
                                'messageId': '010a017745aebf6f-aaddaeab-8091-4930-8c9e-34279e23950c-000000',
                                'subject': 'test2',
                            },
                        },
                        'eventType': 'Delivery',
                    }
                }
            }
        ]
    }

    # noinspection PyPep8Naming
    def mocked_queue_name(QueueName):  # NOSONAR
        assert QueueName == expected_queue_name
        return mock_queue

    # noinspection PyPep8Naming
    def mocked_send_message(MessageBody):  # NOSONAR
        assert MessageBody
        envelope = json.loads(base64.b64decode(MessageBody))
        assert envelope['properties']['delivery_info']['routing_key'] == ROUTING_KEY
        message_body = json.loads(base64.b64decode(envelope['body']))
        assert message_body['args'][0]['Message'] == event['Records'][0]['Sns']['Message']

    mock_queue.send_message.side_effect = mocked_send_message

    mock_sqs = mocker.Mock()
    mock_sqs.get_queue_by_name.side_effect = mocked_queue_name

    mock_boto = mocker.Mock()
    mock_boto.resource.return_value = mock_sqs

    mocker.patch(CALLBACK_LAMBDA_BOTO, new=mock_boto)

    lambda_handler(event, mocker.Mock())
