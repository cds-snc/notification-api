import pytest
import botocore

from app.celery.exceptions import NonRetryableException
from app.clients.sms.aws_pinpoint import AwsPinpointClient, AwsPinpointException


TEST_CONTENT = 'test content'
TEST_ID = 'some-app-id'
TEST_MESSAGE_ID = 'message-id'
TEST_RECIPIENT_NUMBER = '+100000000'
TEST_REFERENCE = 'test notification id'


@pytest.fixture(scope='function')
def aws_pinpoint_client(notify_api, mocker):
    with notify_api.app_context():
        aws_pinpoint_client = AwsPinpointClient()
        statsd_client = mocker.Mock()
        logger = mocker.Mock()
        aws_pinpoint_client.init_app(
            aws_pinpoint_app_id=TEST_ID,
            aws_region='some-aws-region',
            logger=logger,
            origination_number='+10000000000',
            statsd_client=statsd_client,
        )
        return aws_pinpoint_client


@pytest.fixture(scope='function')
def boto_mock(aws_pinpoint_client, mocker):
    boto_mock = mocker.patch.object(aws_pinpoint_client, '_client', create=True)
    return boto_mock


def test_send_sms_successful_returns_aws_pinpoint_response_messageid(aws_pinpoint_client, boto_mock):
    boto_mock.send_messages.return_value = {
        'MessageResponse': {
            'ApplicationId': TEST_ID,
            'RequestId': 'request-id',
            'Result': {
                TEST_RECIPIENT_NUMBER: {
                    'DeliveryStatus': 'SUCCESSFUL',
                    'MessageId': TEST_MESSAGE_ID,
                    'StatusCode': 200,
                    'StatusMessage': f'MessageId: {TEST_MESSAGE_ID}',
                }
            },
        }
    }

    response = aws_pinpoint_client.send_sms(TEST_RECIPIENT_NUMBER, TEST_CONTENT, TEST_REFERENCE)

    assert response == TEST_MESSAGE_ID


def test_send_sms_with_service_sender_number(aws_pinpoint_client, boto_mock):
    test_sender = '+12222222222'

    boto_mock.send_messages.return_value = {
        'MessageResponse': {
            'ApplicationId': TEST_ID,
            'RequestId': 'request-id',
            'Result': {
                TEST_RECIPIENT_NUMBER: {
                    'DeliveryStatus': 'SUCCESSFUL',
                    'MessageId': TEST_MESSAGE_ID,
                    'StatusCode': 200,
                    'StatusMessage': f'MessageId: {TEST_MESSAGE_ID}',
                }
            },
        }
    }

    aws_pinpoint_client.send_sms(TEST_RECIPIENT_NUMBER, TEST_CONTENT, TEST_REFERENCE, sender=test_sender)

    message_request_payload = {
        'Addresses': {TEST_RECIPIENT_NUMBER: {'ChannelType': 'SMS'}},
        'MessageConfiguration': {
            'SMSMessage': {'Body': TEST_CONTENT, 'MessageType': 'TRANSACTIONAL', 'OriginationNumber': test_sender}
        },
    }

    boto_mock.send_messages.assert_called_with(ApplicationId=TEST_ID, MessageRequest=message_request_payload)


def test_send_sms_throws_aws_pinpoint_exception(aws_pinpoint_client, boto_mock):
    invalid_recipient_number = '+1000'

    error_response = {
        'Error': {
            'Code': 400,
            'Message': {
                'RequestID': 'id',
                'Message': 'BadRequestException',
            },
        }
    }

    boto_mock.send_messages.side_effect = botocore.exceptions.ClientError(error_response, 'exception')

    with pytest.raises(AwsPinpointException) as exception:
        aws_pinpoint_client.send_sms(invalid_recipient_number, TEST_CONTENT, TEST_REFERENCE)

    assert 'BadRequestException' in str(exception.value)
    aws_pinpoint_client.statsd_client.incr.assert_called_with('clients.pinpoint.error')


@pytest.mark.parametrize('delivery_status', ['TEMPORARY_FAILURE', 'THROTTLED', 'TIMEOUT', 'UNKNOWN_FAILURE'])
def test_send_sms_returns_result_with_aws_pinpoint_error_delivery_status(
    aws_pinpoint_client, boto_mock, delivery_status
):
    opted_out_number = '+12222222222'

    boto_mock.send_messages.return_value = {
        'MessageResponse': {
            'ApplicationId': TEST_ID,
            'RequestId': 'request-id',
            'Result': {
                TEST_RECIPIENT_NUMBER: {
                    'DeliveryStatus': delivery_status,
                    'MessageId': TEST_MESSAGE_ID,
                    'StatusCode': 400,
                    'StatusMessage': 'Some Error Message',
                }
            },
        }
    }

    with pytest.raises(AwsPinpointException):
        aws_pinpoint_client.send_sms(TEST_RECIPIENT_NUMBER, TEST_CONTENT, TEST_REFERENCE, sender=opted_out_number)

    aws_pinpoint_client.statsd_client.incr.assert_called_with(
        f'clients.pinpoint.delivery-status.{delivery_status.lower()}'
    )


@pytest.mark.parametrize(
    'delivery_status',
    [
        'DUPLICATE',
        'OPT_OUT',
        'PERMANENT_FAILURE',
    ],
)
def test_send_sms_returns_result_with_non_retryable_error_delivery_status(
    aws_pinpoint_client, boto_mock, delivery_status
):
    opted_out_number = '+12222222222'

    boto_mock.send_messages.return_value = {
        'MessageResponse': {
            'ApplicationId': TEST_ID,
            'RequestId': 'request-id',
            'Result': {
                TEST_RECIPIENT_NUMBER: {
                    'DeliveryStatus': delivery_status,
                    'MessageId': TEST_MESSAGE_ID,
                    'StatusCode': 400,
                    'StatusMessage': 'Some Error Message',
                }
            },
        }
    }

    with pytest.raises(NonRetryableException):
        aws_pinpoint_client.send_sms(TEST_RECIPIENT_NUMBER, TEST_CONTENT, TEST_REFERENCE, sender=opted_out_number)

    aws_pinpoint_client.statsd_client.incr.assert_called_with(
        f'clients.pinpoint.delivery-status.{delivery_status.lower()}'
    )
