import json

import pytest
from botocore.exceptions import ClientError

from app.callback.sqs_client import SQSClient

from botocore.stub import Stubber


@pytest.fixture(scope='function')
def sqs_client(notify_api, mocker):
    with notify_api.app_context():
        sqs_client = SQSClient()
        statsd_client = mocker.Mock()
        logger = mocker.Mock()
        sqs_client.init_app(aws_region='some-aws-region', logger=logger, statsd_client=statsd_client)
        return sqs_client


@pytest.fixture()
def sqs_stub(sqs_client):
    with Stubber(sqs_client._client) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


@pytest.mark.parametrize(
    ['message_attributes', 'expected_attributes'],
    [
        (
            {'CallbackType': {'DataType': 'String', 'StringValue': 'foo'}},
            {
                'CallbackType': {'DataType': 'String', 'StringValue': 'foo'},
                'ContentType': {'StringValue': 'application/json', 'DataType': 'String'},
            },
        ),
        (None, {'ContentType': {'StringValue': 'application/json', 'DataType': 'String'}}),
    ],
)
def test_send_message_successful_returns_response_body(sqs_stub, sqs_client, message_attributes, expected_attributes):
    url = 'http://some_url'
    body = {'message': 'hello'}
    message_attributes = message_attributes
    message_id = 'some-id'
    sqs_stub.add_response(
        'send_message',
        expected_params={'QueueUrl': url, 'MessageBody': json.dumps(body), 'MessageAttributes': expected_attributes},
        service_response={'MessageId': message_id},
    )

    response = sqs_client.send_message(url, body, message_attributes)
    assert response['MessageId'] == message_id


@pytest.mark.parametrize(
    ['message_attributes', 'expected_attributes'],
    [
        (
            {'CallbackType': {'DataType': 'String', 'StringValue': 'foo'}},
            {
                'CallbackType': {'DataType': 'String', 'StringValue': 'foo'},
                'ContentType': {'StringValue': 'application/json', 'DataType': 'String'},
            },
        ),
        (None, {'ContentType': {'StringValue': 'application/json', 'DataType': 'String'}}),
    ],
)
def test_send_message_successful_with_fifo_returns_response_body(
    sqs_stub, sqs_client, message_attributes, expected_attributes
):
    url = 'http://some_url/sample_notification_url.fifo'
    body = {'message': 'hello'}
    message_attributes = message_attributes
    message_id = 'some-id'
    sqs_stub.add_response(
        'send_message',
        expected_params={
            'QueueUrl': url,
            'MessageBody': json.dumps(body),
            'MessageAttributes': expected_attributes,
            'MessageGroupId': url,
        },
        service_response={'MessageId': message_id},
    )

    response = sqs_client.send_message(url, body, message_attributes)
    assert response['MessageId'] == message_id


def test_send_message_raises_client_error_on_client_exception(sqs_stub, sqs_client):
    url = 'http://some_url'
    body = {'message': 'hello'}
    message_attributes = {}
    sqs_stub.add_client_error(
        'send_message',
        expected_params={
            'QueueUrl': url,
            'MessageBody': json.dumps(body),
            'MessageAttributes': {'ContentType': {'StringValue': 'application/json', 'DataType': 'String'}},
        },
    )

    with pytest.raises(ClientError):
        sqs_client.send_message(url, body, message_attributes)
