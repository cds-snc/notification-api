from datetime import datetime

import botocore
from app.feature_flags import FeatureFlag
import pytest

from app.celery.exceptions import NonRetryableException, RetryableException
from app.clients.sms import SmsStatusRecord
from app.clients.sms.aws_pinpoint import AwsPinpointClient, AwsPinpointException
from app.constants import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    PINPOINT_PROVIDER,
    STATUS_REASON_BLOCKED,
    STATUS_REASON_INVALID_NUMBER,
    STATUS_REASON_RETRYABLE,
    STATUS_REASON_UNDELIVERABLE,
)
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
            aws_pinpoint_v2_configset='dev',
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
    'store_value, info_calls, warn_calls',
    [(False, 1, 0), ('anything', 1, 0), (1, 1, 0), (0, 1, 0), (None, 1, 1)],
    ids=['boolean_check', 'found_in_redis', 'value_is_1', 'value_is_zero', 'not_in_redis'],
)
def test_send_sms_does_not_log_if_sms_replay(mocker, aws_pinpoint_client, store_value, info_calls, warn_calls):
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
    assert aws_pinpoint_client.logger.info.call_count == info_calls
    assert aws_pinpoint_client.logger.warning.call_count == warn_calls


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


@pytest.mark.parametrize(
    ['delivery_status', 'test_exception'],
    [
        ('TEMPORARY_FAILURE', RetryableException),
        ('THROTTLED', RetryableException),
        ('UNKNOWN_FAILURE', AwsPinpointException),
    ],
)
def test_send_sms_returns_result_with_aws_pinpoint_error_delivery_status(
    aws_pinpoint_client, pinpoint_client_mock, delivery_status, test_exception
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

    with pytest.raises(test_exception):
        aws_pinpoint_client.send_sms(TEST_RECIPIENT_NUMBER, TEST_CONTENT, TEST_REFERENCE, sender=opted_out_number)


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


@pytest.mark.parametrize(
    ['status', 'test_exception'],
    [
        ('THROTTLED', RetryableException),
        ('TEMPORARY_FAILURE', RetryableException),
        ('UNKNOWN_FAILURE', AwsPinpointException),
        ('PERMANENT_FAILURE', NonRetryableException),
        ('OPT_OUT', NonRetryableException),
        ('DUPLICATE', NonRetryableException),
    ],
)
def test_send_sms_post_message_request_validate_response_raises_exception(
    aws_pinpoint_client,
    status,
    test_exception,
):
    result = {
        'DeliveryStatus': status,
        'MessageId': 'MessageId-string',
        'StatusCode': 111,
        'StatusMessage': 'StatusMessage-string',
        'UpdatedToken': 'UpdatedToken-string',
    }
    with pytest.raises(test_exception):
        aws_pinpoint_client._validate_response(result, '123456')


@pytest.mark.parametrize('status', ('PERMANENT_FAILURE', 'OPT_OUT', 'DUPLICATE'))
def test_send_sms_post_message_request_validate_response_raises_invalid_provider_exception(
    aws_pinpoint_client,
    status,
):
    result = {
        'DeliveryStatus': status,
        'MessageId': 'MessageId-string',
        'StatusCode': 111,
        'StatusMessage': 'provided number does not exist',
        'UpdatedToken': 'UpdatedToken-string',
    }
    with pytest.raises(InvalidProviderException):
        aws_pinpoint_client._validate_response(result, '123456')


def test_send_sms_post_message_request_validate_response_happy_path(aws_pinpoint_client):
    result = {
        'DeliveryStatus': 'SUCCESS',
        'MessageId': 'MessageId-string',
        'StatusCode': 111,
        'StatusMessage': 'StatusMessage-string',
        'UpdatedToken': 'UpdatedToken-string',
    }
    # No exceptions raised
    aws_pinpoint_client._validate_response(result, '123456')


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


@pytest.mark.parametrize('pinpoint_v2_enabled', (False, True))
def test_translate_delivery_status_pinpoint_sms_v1_successful(aws_pinpoint_client, mocker, pinpoint_v2_enabled):
    """Test translate_delivery_status for PinpointSMSV1 delivery status with and without PinpointSMSVoiceV2 feature enabled"""

    mocker.patch.dict('os.environ', {'PINPOINT_SMS_VOICE_V2': str(pinpoint_v2_enabled)})

    # Sample V1 delivery status message
    v1_delivery_message = {
        'event_type': '_SMS.SUCCESS',
        'event_timestamp': 1722427200000,
        'arrival_timestamp': 1722427200000,
        'event_version': '3.1',
        'application': {'app_id': '123', 'sdk': {}},
        'client': {'client_id': '123456789012'},
        'device': {'platform': {}},
        'session': {},
        'attributes': {
            'sender_request_id': 'e669df09-642b-4168-8563-3e5a4f9dcfbf',
            'campaign_activity_id': '1234',
            'origination_phone_number': '+15555555555',
            'destination_phone_number': '+15555555555',
            'record_status': 'DELIVERED',
            'iso_country_code': 'US',
            'treatment_id': '0',
            'number_of_message_parts': 1,
            'message_id': 'test-message-id-123',
            'message_type': 'Transactional',
            'campaign_id': '12345',
        },
        'metrics': {
            'price_in_millicents_usd': 645.0,
        },
        'awsAccountId': '123456789012',
    }

    result = aws_pinpoint_client.translate_delivery_status(v1_delivery_message)

    expected = SmsStatusRecord(
        payload=None,
        reference='test-message-id-123',
        status=NOTIFICATION_DELIVERED,
        status_reason=None,
        provider=PINPOINT_PROVIDER,
        message_parts=1,
        price_millicents=645,
        provider_updated_at=datetime(2024, 7, 31, 12, 0),
    )

    assert result == expected


def test_translate_delivery_status_pinpoint_sms_voice_v2_successful(aws_pinpoint_client, mocker):
    """Test translate_delivery_status for PinpointSMSVoiceV2 format with successful delivery"""

    mock_feature_flag = mocker.Mock(FeatureFlag)
    mock_feature_flag.value = 'PINPOINT_SMS_VOICE_V2'
    mocker.patch('app.feature_flags.os.getenv', return_value='True')

    # Sample V2 delivery status message
    v2_delivery_message = {
        'eventType': 'TEXT_SUCCESSFUL',
        'eventVersion': '1.0',
        'messageId': 'test-message-id-123',
        'messageStatus': 'DELIVERED',
        'destinationPhoneNumber': '+1234567890',
        'totalMessagePrice': 0.075,
        'totalMessageParts': 1,
        'eventTimestamp': 1722427200000,
    }

    result = aws_pinpoint_client.translate_delivery_status(v2_delivery_message)

    expected = SmsStatusRecord(
        payload=None,
        reference='test-message-id-123',
        status=NOTIFICATION_DELIVERED,
        status_reason=None,
        provider=PINPOINT_PROVIDER,
        message_parts=1,
        price_millicents=75,
        provider_updated_at=datetime(2024, 7, 31, 12, 0),
    )

    assert result == expected


def test_translate_delivery_status_pinpoint_sms_voice_v2_missing_required_fields(aws_pinpoint_client, mocker):
    """Test translate_delivery_status raises NonRetryableException when required V2 fields are missing"""

    mock_feature_flag = mocker.Mock(FeatureFlag)
    mock_feature_flag.value = 'PINPOINT_SMS_VOICE_V2'
    mocker.patch('app.feature_flags.os.getenv', return_value='True')

    # V2 delivery status message with data but missing required fields (eventType and messageId)
    v2_delivery_message = {
        'eventVersion': '1.0',
        'messageStatus': 'TEXT_DELIVERED',
        'destinationPhoneNumber': '+1234567890',
        'totalMessagePrice': 0.075,
        'totalMessageParts': 1,
        'eventTimestamp': 1722427200000,
        'sourcePhoneNumber': '+19876543210',
        'isoCountryCode': 'US',
        'messageType': 'TRANSACTIONAL',
    }

    with pytest.raises(NonRetryableException):
        aws_pinpoint_client.translate_delivery_status(v2_delivery_message)


# Test for PointpointSMSVoiceV2 event type and current status mapping
# Tests pass, but we need to ensure that the event type and status mapping is correct.
# This does not include all possible event types, but covers the main ones.
# https://docs.aws.amazon.com/sms-voice/latest/userguide/configuration-sets-event-types.html
@pytest.mark.skip(reason='#1829 - Skipping until we can confirm the event type and status mapping is correct')
@pytest.mark.parametrize(
    'event_type,message_status,expected_status,expected_status_reason',
    [
        ('TEXT_DELIVERED', 'DELIVERED', NOTIFICATION_DELIVERED, None),
        ('TEXT_SUCCESSFUL', 'SUCCESSFUL', NOTIFICATION_DELIVERED, None),
        ('TEXT_BLOCKED', 'BLOCKED', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        ('TEXT_INVALID', 'INVALID', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_INVALID_NUMBER),
        ('TEXT_CARRIER_BLOCKED', 'CARRIER_BLOCKED', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        ('TEXT_SPAM', 'SPAM', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        ('TEXT_UNREACHABLE', 'UNREACHABLE', NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        ('TEXT_UNKNOWN', 'UNKNOWN', NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        ('TEXT_INVALID_MESSAGE', 'INVALID_MESSAGE', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
    ],
)
def test_translate_delivery_status_pinpoint_sms_voice_v2_additional_events(
    aws_pinpoint_client, mocker, event_type, message_status, expected_status, expected_status_reason
):
    """Test translate_delivery_status for additional PinpointSMSVoiceV2 event types"""

    mock_feature_flag = mocker.Mock(FeatureFlag)
    mock_feature_flag.value = 'PINPOINT_SMS_VOICE_V2'
    mocker.patch('app.feature_flags.os.getenv', return_value='True')

    # Sample V2 delivery status message with various event types
    v2_delivery_message = {
        'eventType': event_type,
        'eventVersion': '1.0',
        'messageId': 'test-message-id-456',
        'messageStatus': message_status,
        'destinationPhoneNumber': '+1234567890',
        'totalMessagePrice': 0.05,
        'totalMessageParts': 1,
        'eventTimestamp': 1722427200000,
    }

    result = aws_pinpoint_client.translate_delivery_status(v2_delivery_message)

    expected = SmsStatusRecord(
        payload=None,
        reference='test-message-id-456',
        status=expected_status,
        status_reason=expected_status_reason,
        provider=PINPOINT_PROVIDER,
        message_parts=1,
        price_millicents=50,
        provider_updated_at=datetime(2024, 7, 31, 12, 0),
    )

    assert result == expected
