import botocore
import json
import pytest

from lambda_functions.two_way_sms.two_way_sms_lambda import two_way_sms_handler

VALID_TEST_RECIPIENT_PHONE_NUMBER = '+16502532222'


@pytest.fixture(scope='function')
def mock_boto(mocker):
    mock_boto = mocker.Mock()
    mocker.patch('lambda_functions.two_way_sms.two_way_sms_lambda.boto3', new=mock_boto)

    return mock_boto


def test_handler_with_sns_and_start_keyword_success(mocker, mock_boto):
    mock_sns = mocker.Mock()
    mock_success_response = {
        'ResponseMetadata': {
            'RequestId': 'request-id',
            'HTTPStatusCode': 200,
            'HTTPHeaders': {
                'date': 'Fri, 29 Jan 2021 22:05:47 GMT',
                'content-type': 'application/json',
                'content-length': '303',
                'connection': 'keep-alive',
                'x-amzn-requestid': 'request-id',
                'access-control-allow-origin': '*',
                'x-amz-apigw-id': 'other-id',
                'cache-control': 'no-store',
                'x-amzn-trace-id': 'trace-id',
            },
            'RetryAttempts': 0,
        },
        'MessageResponse': {
            'ApplicationId': 'test-app-id',
            'RequestId': 'request-id',
            'Result': {
                VALID_TEST_RECIPIENT_PHONE_NUMBER: {
                    'DeliveryStatus': 'SUCCESSFUL',
                    'MessageId': 'test-message-id',
                    'StatusCode': 200,
                    'StatusMessage': 'MessageId: test-message-id',
                }
            },
        },
    }

    mock_sns.opt_in_phone_number.return_value = mock_success_response
    event = create_event('start')
    mock_boto.client.return_value = mock_sns

    success_status_code = mock_success_response['ResponseMetadata']['HTTPStatusCode']
    success_result = mock_success_response['MessageResponse']['Result'][VALID_TEST_RECIPIENT_PHONE_NUMBER]

    response = two_way_sms_handler(event, mocker.Mock())
    mock_sns.opt_in_phone_number.assert_called_once()

    assert response['StatusCode'] == success_status_code
    assert response['DeliveryStatus'] == success_result['DeliveryStatus']
    assert response['DeliveryStatusCode'] == success_result['StatusCode']
    assert response['DeliveryStatusMessage'] == success_result['StatusMessage']


def test_handler_with_sns_start_keyword_failure(mocker, mock_boto):
    mock_sns = mocker.Mock()
    failure_response = {
        'Error': {
            'Code': 400,
            'Message': {
                'RequestID': 'id',
                'Message': 'BadRequestException',
            },
        },
        'ResponseMetadata': {
            'RequestId': 'request-id',
            'HTTPStatusCode': 400,
            'HTTPHeaders': {
                'date': 'Fri, 29 Jan 2021 01:07:00 GMT',
                'content-type': 'application/json',
                'content-length': '303',
                'connection': 'keep-alive',
                'x-amzn-requestid': 'request-id',
                'access-control-allow-origin': '*',
                'x-amz-apigw-id': 'some-id',
                'cache-control': 'no-store',
                'x-amzn-trace-id': 'trace-id',
            },
            'RetryAttempts': 0,
        },
    }

    mock_boto.client.side_effect = botocore.exceptions.ClientError(failure_response, 'exception')

    event = create_event('start')

    mock_boto.client.return_value = mock_sns

    with pytest.raises(Exception) as exception:
        two_way_sms_handler(event, mocker.Mock())

    assert str(failure_response['ResponseMetadata']['HTTPStatusCode']) in str(exception.value)


def test_handler_with_sns_start_keyword_permanent_failure(mocker, mock_boto):
    mock_sns = mocker.Mock()
    phone_number_that_has_maxed_opt_out = VALID_TEST_RECIPIENT_PHONE_NUMBER

    mock_failure_response = {
        'ResponseMetadata': {
            'RequestId': 'd090f18f-b13a-4771-913e-3162c10968a8',
            'HTTPStatusCode': 200,
            'HTTPHeaders': {
                'date': 'Fri, 29 Jan 2021 01:07:00 GMT',
                'content-type': 'application/json',
                'content-length': '303',
                'connection': 'keep-alive',
                'x-amzn-requestid': 'request-id',
                'access-control-allow-origin': '*',
                'x-amz-apigw-id': 'Z4vkMEaxPHMFvkg=',
                'cache-control': 'no-store',
                'x-amzn-trace-id': 'trace-id',
            },
            'RetryAttempts': 0,
        },
        'MessageResponse': {
            'ApplicationId': 'pinpoint-project-id',
            'RequestId': 'request-id',
            'Result': {
                phone_number_that_has_maxed_opt_out: {
                    'DeliveryStatus': 'PERMANENT_FAILURE',
                    'MessageId': 'message-id',
                    'StatusCode': 400,
                    'StatusMessage': 'Phone number is opted out',
                }
            },
        },
    }

    mock_sns.opt_in_phone_number.return_value = mock_failure_response

    event = create_event('start')

    mock_boto.client.return_value = mock_sns

    with pytest.raises(Exception):
        response = two_way_sms_handler(event, mocker.Mock())
        failure_result = mock_failure_response['MessageResponse']['Result'][phone_number_that_has_maxed_opt_out]

        mock_sns.opt_in_phone_number.assert_called_once()
        assert response['StatusCode'] == mock_failure_response['ResponseMetadata']['HTTPStatusCode']
        assert response['DeliveryStatus'] == failure_result['DeliveryStatus']
        assert response['DeliveryStatusCode'] == failure_result['StatusCode']
        assert response['DeliveryStatusMessage'] == failure_result['StatusMessage']


def test_sns_submits_to_topic_when_opt_in_phone_number_throws_client_exception(mocker, mock_boto):
    mock_sns = mocker.Mock()

    failure_response = {
        'Error': {
            'Code': 400,
            'Message': {
                'RequestID': 'id',
                'Message': 'InvalidParameter',
            },
        },
        'ResponseMetadata': {
            'RequestId': 'request-id',
            'HTTPStatusCode': 400,
            'HTTPHeaders': {
                'date': 'Fri, 29 Jan 2021 01:07:00 GMT',
                'content-type': 'application/json',
                'content-length': '303',
                'connection': 'keep-alive',
                'x-amzn-requestid': 'request-id',
                'access-control-allow-origin': '*',
                'x-amz-apigw-id': 'some-id',
                'cache-control': 'no-store',
                'x-amzn-trace-id': 'trace-id',
            },
            'RetryAttempts': 0,
        },
    }

    expected_error_message = {
        'sns_opt_in_request_id': failure_response['ResponseMetadata']['RequestId'],
        'error_code': failure_response['Error']['Code'],
        'error_message': failure_response['Error']['Message'],
    }

    mock_sns.opt_in_phone_number.side_effect = botocore.exceptions.ClientError(failure_response, 'exception')

    event = create_event('start')

    mock_boto.client.return_value = mock_sns

    two_way_sms_handler(event, mocker.Mock())

    mock_sns.publish.assert_called_once_with(
        TopicArn='test-failure-topic-arn', Message=json.dumps(expected_error_message), Subject='AWS SNS Opt-in Failure'
    )


def test_handler_with_sns_start_keyword_already_opted_in(mocker, mock_boto):
    mock_sns = mocker.Mock()

    mock_minimal_response = {
        'ResponseMetadata': {
            'RequestId': 'some request id',
            'HTTPStatusCode': 200,
            'HTTPHeaders': {
                'date': 'Fri, 29 Jan 2021 01:07:00 GMT',
                'content-type': 'application/json',
                'content-length': '303',
                'connection': 'keep-alive',
                'x-amzn-requestid': 'request-id',
                'access-control-allow-origin': '*',
                'x-amz-apigw-id': 'some id',
                'cache-control': 'no-store',
                'x-amzn-trace-id': 'trace-id',
            },
            'RetryAttempts': 0,
        }
    }

    mock_sns.opt_in_phone_number.return_value = mock_minimal_response
    event = create_event('start')
    mock_boto.client.return_value = mock_sns

    response = two_way_sms_handler(event, mocker.Mock())

    mock_sns.opt_in_phone_number.assert_called_once()
    assert response['StatusCode'] == mock_minimal_response['ResponseMetadata']['HTTPStatusCode']


def test_handler_with_pinpoint_and_unsupported_keyword_success(mocker, mock_boto):
    mock_pinpoint = mocker.Mock()

    mock_pinpoint.send_messages.return_value = {
        'MessageResponse': {
            'ApplicationId': 'test-app-id',
            'EndpointResult': {
                'some endpoint': {
                    'Address': 'some address',
                    'DeliveryStatus': 'SUCCESSFUL',
                    'MessageId': 'test-message-id',
                    'StatusCode': 200,
                    'StatusMessage': 'MessageId: test-message-id',
                    'UpdatedToken': 'some token',
                }
            },
            'RequestId': 'request-id',
            'Result': {
                VALID_TEST_RECIPIENT_PHONE_NUMBER: {
                    'DeliveryStatus': 'SUCCESSFUL',
                    'MessageId': 'test-message-id',
                    'StatusCode': 200,
                    'StatusMessage': 'MessageId: test-message-id',
                }
            },
        }
    }

    event = create_event('unsupported keywords')

    mock_boto.client.return_value = mock_pinpoint

    response = two_way_sms_handler(event, mocker.Mock())
    mock_pinpoint.send_messages.assert_called_once()

    assert response['StatusCode'] == 200


def test_handler_with_pinpoint_and_unsupported_keyword_failure(mocker, mock_boto):
    mock_pinpoint = mocker.Mock()
    failure_response = {
        'Error': {
            'Code': 400,
            'Message': {
                'RequestID': 'id',
                'Message': 'BadRequestException',
            },
        }
    }

    mock_boto.client.return_value = mock_pinpoint

    mock_boto.client.side_effect = botocore.exceptions.ClientError(failure_response, 'exception')

    event = create_event('other words')

    with pytest.raises(Exception) as exception:
        two_way_sms_handler(event, mocker.Mock())

    assert str(failure_response['Error']['Code']) in str(exception.value)
    assert str(failure_response['Error']['Message']['Message']) in str(exception.value)


def create_event(message_body: str) -> dict:
    return {
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
                    'MessageId': 'message-id',
                    'Message': '{'
                    f'"originationNumber":"{VALID_TEST_RECIPIENT_PHONE_NUMBER}",'
                    '"destinationNumber":"+from_number",'
                    '"messageKeyword":"keyword_blah",'
                    f'"messageBody":"{message_body}",'
                    '"inboundMessageId":"inbound-message-id",'
                    '"previousPublishedMessageId":"prev-pub-msg-id"}',
                    'MessageAttributes': {
                        'Test': {'Type': 'String', 'Value': 'TestString'},
                        'TestBinary': {'Type': 'Binary', 'Value': 'TestBinary'},
                    },
                    'Type': 'Notification',
                    'UnsubscribeUrl': 'some_url',
                    'TopicArn': 'some-arn',
                    'Subject': 'some-test-thing',
                },
            }
        ]
    }
