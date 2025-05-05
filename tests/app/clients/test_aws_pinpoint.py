import pytest
import botocore

from app.celery.exceptions import NonRetryableException, RetryableException
from app.clients.sms.aws_pinpoint import AwsPinpointClient, AwsPinpointException
from app.exceptions import InvalidProviderException

TEST_CONTENT = 'test content'
TEST_ID = 'some-app-id'
TEST_MESSAGE_ID = 'message-id'
TEST_RECIPIENT_NUMBER = '+100000000'
TEST_REFERENCE = 'test notification id'


@pytest.fixture
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


@pytest.fixture
def pinpoint_client_mock(aws_pinpoint_client, mocker):
    pinpoint_client_mock = mocker.patch.object(aws_pinpoint_client, '_pinpoint_client', create=True)
    return pinpoint_client_mock


@pytest.mark.parametrize('sender', (None, '+12222222222'))
@pytest.mark.parametrize('PINPOINT_SMS_VOICE_V2', ('False', 'True'))
def test_send_sms_successful_returns_aws_pinpoint_response_messageid(
    PINPOINT_SMS_VOICE_V2, sender, mocker, aws_pinpoint_client, monkeypatch
):
    monkeypatch.setenv('PINPOINT_SMS_VOICE_V2', PINPOINT_SMS_VOICE_V2)

    if PINPOINT_SMS_VOICE_V2 == 'True':
        client_mock = mocker.patch.object(aws_pinpoint_client, '_pinpoint_sms_voice_v2_client', create=True)
        client_mock.send_text_message.return_value = {'MessageId': TEST_MESSAGE_ID}
    else:
        client_mock = mocker.patch.object(aws_pinpoint_client, '_pinpoint_client', create=True)
        client_mock.send_messages.return_value = {
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

    response = aws_pinpoint_client.send_sms(TEST_RECIPIENT_NUMBER, TEST_CONTENT, TEST_REFERENCE, sender=sender)
    assert response == TEST_MESSAGE_ID


@pytest.mark.parametrize(
    'store_value, logger_calls',
    [(False, 1), ('anything', 1), (1, 1), (0, 1), (None, 2)],
    ids=['boolean_check', 'found_in_redis', 'value_is_1', 'value_is_zero', 'not_in_redis'],
)
def test_send_sms_does_not_log_if_sms_replay(mocker, aws_pinpoint_client, store_value, logger_calls):
    """We use this log for tracking accurate metrics, it is critical"""
    client_mock = mocker.patch.object(aws_pinpoint_client, '_pinpoint_client', create=True)
    mocker.patch('app.redis_store.get', return_value=store_value)
    client_mock.send_messages.return_value = {
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
    aws_pinpoint_client.send_sms(TEST_RECIPIENT_NUMBER, TEST_CONTENT, TEST_REFERENCE)
    assert aws_pinpoint_client.logger.info.call_count == logger_calls


@pytest.mark.parametrize('PINPOINT_SMS_VOICE_V2', ('False', 'True'))
def test_send_sms_throws_aws_pinpoint_exception(PINPOINT_SMS_VOICE_V2, aws_pinpoint_client, mocker, monkeypatch):
    monkeypatch.setenv('PINPOINT_SMS_VOICE_V2', PINPOINT_SMS_VOICE_V2)

    error_response = {
        'Error': {
            'Code': 400,
            'Message': {
                'RequestID': 'id',
                'Message': 'BadRequestException',
            },
        }
    }

    if PINPOINT_SMS_VOICE_V2 == 'True':
        client_mock = mocker.patch.object(aws_pinpoint_client, '_pinpoint_sms_voice_v2_client', create=True)
        client_mock.send_text_message.side_effect = botocore.exceptions.ClientError(error_response, 'exception')
    else:
        client_mock = mocker.patch.object(aws_pinpoint_client, '_pinpoint_client', create=True)
        client_mock.send_messages.side_effect = botocore.exceptions.ClientError(error_response, 'exception')

    with pytest.raises(AwsPinpointException) as exception:
        aws_pinpoint_client.send_sms('+1000', TEST_CONTENT, TEST_REFERENCE)

    assert 'BadRequestException' in str(exception.value)
    aws_pinpoint_client.statsd_client.incr.assert_called_with('clients.pinpoint.error')


@pytest.mark.parametrize('delivery_status', ['TEMPORARY_FAILURE', 'THROTTLED', 'TIMEOUT', 'UNKNOWN_FAILURE'])
def test_send_sms_returns_result_with_aws_pinpoint_error_delivery_status(
    aws_pinpoint_client, pinpoint_client_mock, delivery_status
):
    """
    This test is only applicable to the Pinpoint client (not V2).  The V2 client response does not contain
    this verbose response.
    """
    opted_out_number = '+12222222222'

    pinpoint_client_mock.send_messages.return_value = {
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


@pytest.mark.parametrize('delivery_status', ['DUPLICATE', 'OPT_OUT', 'PERMANENT_FAILURE'])
def test_send_sms_returns_result_with_non_retryable_error_delivery_status(
    aws_pinpoint_client, pinpoint_client_mock, delivery_status
):
    """
    This test is only applicable to the Pinpoint client (not V2).  The V2 client response does not contain
    this verbose response.
    """
    opted_out_number = '+12222222222'

    pinpoint_client_mock.send_messages.return_value = {
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


def test_send_sms_raises_invalid_provider_error_with_invalide_number(aws_pinpoint_client, pinpoint_client_mock):
    """
    This test is only applicable to the Pinpoint client (not V2).  The V2 client response does not contain
    this verbose response.
    """
    delivery_status = 'PERMANENT_FAILURE'
    invalid_number = '+12223334444'

    pinpoint_client_mock.send_messages.return_value = {
        'MessageResponse': {
            'ApplicationId': TEST_ID,
            'RequestId': 'request-id',
            'Result': {
                TEST_RECIPIENT_NUMBER: {
                    'DeliveryStatus': delivery_status,
                    'MessageId': TEST_MESSAGE_ID,
                    'StatusCode': 400,
                    'StatusMessage': 'The provided number does not exist or does not belong to the account',
                }
            },
        }
    }

    with pytest.raises(InvalidProviderException):
        aws_pinpoint_client.send_sms(TEST_RECIPIENT_NUMBER, TEST_CONTENT, TEST_REFERENCE, sender=invalid_number)

    aws_pinpoint_client.statsd_client.incr.assert_called_with(
        f'clients.pinpoint.delivery-status.{delivery_status.lower()}'
    )


@pytest.mark.parametrize('code', AwsPinpointClient._retryable_v1_codes)
def test_send_sms_post_message_request_raises_retryable_exception(mocker, aws_pinpoint_client, code):
    # These are retryable but expected
    mocker.patch.object(
        aws_pinpoint_client,
        '_post_message_request',
        side_effect=AwsPinpointException(f'Message StatusCode: {code}, StatusMessage:Too many requests.'),
    )
    # Ensure it is converted to RetryableException for exception handling in _handle_delivery_failure
    with pytest.raises(RetryableException):
        aws_pinpoint_client.send_sms(TEST_RECIPIENT_NUMBER, TEST_CONTENT, TEST_REFERENCE)


@pytest.mark.parametrize('code', ('123', '418'))
def test_send_sms_post_message_request_raises_aws_exception(mocker, aws_pinpoint_client, code):
    # These are retryable so we can figure out why the thing exploded
    mocker.patch.object(
        aws_pinpoint_client,
        '_post_message_request',
        side_effect=AwsPinpointException(f"Message StatusCode: {code}, StatusMessage:I'm a teapot"),
    )
    # Ensure it is converted to AwsPinpointException for exception handling in _handle_delivery_failure
    with pytest.raises(AwsPinpointException):
        aws_pinpoint_client.send_sms(TEST_RECIPIENT_NUMBER, TEST_CONTENT, TEST_REFERENCE)
