import os
import pytest
import requests
from lambda_functions.two_way_sms.two_way_sms_v2 import (
    notify_incoming_sms_handler,
    valid_event,
    valid_message_body,
    forward_to_service,
    get_ssm_param_info,
)
from moto import mock_aws
import boto3

LAMBDA_MODULE = 'lambda_functions.two_way_sms.two_way_sms_v2'
DESTINATION_NUMBER = '+12222222222'
INVALID_EVENT = {}
INVALID_EVENT_BODY = {'Records': [{'no_body': {}}]}
VALID_EVENT = {
    'Records': [
        {
            'messageId': 'c5fd0ef6-1145-4ba3-9612-1d8fa7ec6e73',
            'receiptHandle': 'handlesig==',
            'body': '{\n "Type" : "Notification",\n "MessageId" : "guid",\n "TopicArn" : "notify-incoming-sms",\n "Message" : "{\\"originationNumber\\":\\"+11111111111\\",\\"destinationNumber\\":\\"+12222222222\\",\\"messageKeyword\\":\\"KEYWORD_171875617347\\",\\"messageBody\\":\\"Test message\\",\\"inboundMessageId\\":\\"messageid\\"}",\n "Timestamp" : "2022-12-02T04:16:59.606Z",\n "SignatureVersion" : "1",\n "Signature" : "somesig==",\n "SigningCertURL" : "https://someurl/some.pem",\n "UnsubscribeURL" : "https://someurl/?Action=Unsubscribe&SubscriptionArn=notify-incoming-sms"\n}',
            'attributes': {
                'ApproximateReceiveCount': '1',
                'SentTimestamp': '1669954619628',
                'SenderId': '280946605409',
                'ApproximateFirstReceiveTimestamp': '1669954619630',
            },
            'messageAttributes': {},
            'md5OfBody': 'somevalue',
            'eventSource': 'aws:sqs',
            'eventSourceARN': 'notify-incoming-sms',
            'awsRegion': 'some-region',  # noqa
        }
    ]
}

# Test valid event
invalid_none_event = None
invalid_event_empty_event = {}
invalid_event_missing_body = {'Records': [{'no_body': ''}]}


@pytest.mark.parametrize('event', [(invalid_none_event), (invalid_event_empty_event), (invalid_event_missing_body)])
def test_validate_event(mocker, event):
    response = valid_event(event)
    assert response is False


# Test invalid event body
invalid_event_body_empty_body = {}
invalid_event_missing_destinationNumber = {'originationNumber': '+11111111111', 'messageBody': 'message'}
invalid_event_missing_originationNumber = {'destinationNumber': '+12222222222', 'messageBody': 'message'}
invalid_event_missing_messageBody = {'originationNumber': '+11111111111', 'destinationNumber': '+12222222222'}


@pytest.mark.parametrize(
    'event',
    [
        (invalid_event_body_empty_body),
        (invalid_event_missing_destinationNumber),
        (invalid_event_missing_originationNumber),
        (invalid_event_missing_messageBody),
    ],
)
def test_validate_event_body(mocker, event):
    mocker.patch.dict(
        os.environ,
        {
            'AWS_PINPOINT_APP_ID': 'AWS_PINPOINT_APP_ID',
            'DEAD_LETTER_SQS_URL': 'DEAD_LETTER_SQS_URL',
            'LOG_LEVEL': 'DEBUG',
            'RETRY_SQS_URL': 'RETRY_SQS_URL',
            'TIMEOUT': '10',
            'DATABASE_URI_PATH': 'DATABASE_URI_PATH',
            'VETEXT_API_AUTH_SSM_PATH': 'VETEXT_API_AUTH_SSM_PATH',
        },
    )
    response = valid_message_body(event)

    assert response is False


@mock_aws
def test_get_ssm_param_info(mocker):
    param_name = '/auth/token'
    param_value = 'xyz'

    ssm_client = boto3.client('ssm', 'us-gov-west-1')
    ssm_client.put_parameter(Name=param_name, Description='auth token test', Value=param_value, Type='SecureString')

    assert get_ssm_param_info(param_name) == param_value


def test_forward_to_service_success(mocker, requests_mock):
    test_url = 'https://test.url'
    mocker.patch(f'{LAMBDA_MODULE}.get_ssm_param_info', return_value='auth_token')

    requests_mock.post(test_url, json={'things': 'stuff'})

    assert forward_to_service(inbound_sms={}, url=test_url, auth_parameter='auth_param')


def test_forward_to_service_failed_on_empty_url(mocker):
    """
    Test forward to service
    """

    response = forward_to_service({}, '', None)
    assert response is False


def test_forward_to_service_failed_post_on_http_error(mocker):
    mocker.patch(
        f'{LAMBDA_MODULE}.requests.post',
        side_effect=requests.exceptions.HTTPError('http://example.com', 500, 'Error message', {}, None),
    )
    response = forward_to_service({}, 'https://someurl.com', 'None')
    assert response is False


def test_forward_to_service_failed_post_on_request_exception(mocker):
    mocker.patch(f'{LAMBDA_MODULE}.requests.post', side_effect=requests.exceptions.RequestException())
    response = forward_to_service({}, 'https://someurl.com', 'None')
    assert response is False


def test_forward_to_service_failed_on_general_exception(mocker):
    mocker.patch(f'{LAMBDA_MODULE}.requests.post', side_effect=Exception)

    with pytest.raises(Exception):
        forward_to_service({}, 'https://someurl.com', 'None')


# Test Handler
def test_notify_incoming_sms_handler_invalid_event(mocker):
    """
    verify 200 response when event is not valid_event
    """

    sqs_mock = mocker.patch(f'{LAMBDA_MODULE}.push_to_sqs')
    mocker.patch(
        f'{LAMBDA_MODULE}.two_way_sms_table_dict',
        return_value={
            DESTINATION_NUMBER: {
                'service_id': 'someserviceid',
                'url_endpoint': 'https://someurl.com',
                'self_managed': False,
            }
        },
    )

    response = notify_incoming_sms_handler(INVALID_EVENT, None)

    assert response['statusCode'] == 200
    sqs_mock.assert_called_once()


def test_notify_incoming_sms_handler_invalid_event_body(mocker):
    """
    verify 200 response when event is not valid_event body
    """

    sqs_mock = mocker.patch(f'{LAMBDA_MODULE}.push_to_sqs')
    mocker.patch(
        f'{LAMBDA_MODULE}.two_way_sms_table_dict',
        return_value={
            DESTINATION_NUMBER: {
                'service_id': 'someserviceid',
                'url_endpoint': 'https://someurl.com',
                'self_managed': False,
            }
        },
    )

    response = notify_incoming_sms_handler(INVALID_EVENT_BODY, None)

    assert response['statusCode'] == 200
    sqs_mock.assert_called_once()


def test_notify_incoming_sms_handler_failed_request(mocker):
    """
    verify when forward_to_service return False and response 400
    """

    sqs_mock = mocker.patch(f'{LAMBDA_MODULE}.push_to_sqs')
    mocker.patch(
        f'{LAMBDA_MODULE}.requests.post',
        side_effect=requests.exceptions.HTTPError('http://example.com', 500, 'Error message', {}, None),
    )
    mocker.patch(
        f'{LAMBDA_MODULE}.two_way_sms_table_dict',
        return_value={
            DESTINATION_NUMBER: {
                'service_id': 'someserviceid',
                'url_endpoint': 'https://someurl.com',
                'self_managed': False,
            }
        },
    )

    response = notify_incoming_sms_handler(VALID_EVENT, None)

    assert response['statusCode'] == 400
    sqs_mock.assert_called_once()


def test_notify_incoming_sms_handler_phonenumber_not_found_keyerror(mocker):
    # verify push_to_sqs is called once when KeyError is thrown and response 200
    sqs_mock = mocker.patch(f'{LAMBDA_MODULE}.push_to_sqs')
    # trigger the key not existing
    mocker.patch(
        f'{LAMBDA_MODULE}.two_way_sms_table_dict',
        {'+123': {'service_id': 'someserviceid', 'url_endpoint': 'https://someurl.com', 'self_managed': False}},
    )

    response = notify_incoming_sms_handler(VALID_EVENT, None)

    assert response['statusCode'] == 200
    sqs_mock.assert_called_once()


def test_notify_incoming_sms_handler_phonenumber_not_found_exception(mocker):
    # verify push_to_sqs is called when General Exception is thrown and response 200
    sqs_mock = mocker.patch(f'{LAMBDA_MODULE}.push_to_sqs')
    mocker.patch(
        f'{LAMBDA_MODULE}.two_way_sms_table_dict',
        {
            DESTINATION_NUMBER: {
                'service_id': 'someserviceid',
                'url_endpoint': 'https://someurl.com',
                'self_managed': False,
            }
        },
    )

    # trigger forward to service raising an exception
    mocker.patch(f'{LAMBDA_MODULE}.forward_to_service', side_effect=Exception)

    response = notify_incoming_sms_handler(VALID_EVENT, None)

    assert response['statusCode'] == 200
    sqs_mock.assert_called_once()
