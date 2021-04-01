import pytest
from app import aws_sns_client
from flask import current_app


def test_send_sms_successful_returns_aws_sns_response(notify_api, mocker):
    boto_mock = mocker.patch.object(aws_sns_client, '_client', create=True)
    mocker.patch.object(aws_sns_client, 'statsd_client', create=True)

    to = "6135555555"
    content = reference = 'foo'

    with notify_api.app_context():
        aws_sns_client.send_sms(to, content, reference)

    boto_mock.publish.assert_called_once_with(
        PhoneNumber="+16135555555",
        Message=content,
        MessageAttributes={'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': 'Transactional'}}
    )


def test_send_sms_returns_raises_error_if_there_is_no_valid_number_is_found(notify_api, mocker):
    mocker.patch.object(aws_sns_client, '_client', create=True)
    mocker.patch.object(aws_sns_client, 'statsd_client', create=True)

    to = ""
    content = reference = 'foo'

    with pytest.raises(ValueError) as excinfo:
        aws_sns_client.send_sms(to, content, reference)

    assert 'No valid numbers found for SMS delivery' in str(excinfo.value)


def test_send_sms_with_long_code_successful_returns_aws_sns_response(notify_api, mocker):
    boto_mock = mocker.patch.object(aws_sns_client, '_long_codes_client', create=True)
    mocker.patch.object(aws_sns_client, 'statsd_client', create=True)

    sender = "+19025551234"
    to = "6135555555"
    content = reference = 'foo'

    with notify_api.app_context():
        aws_sns_client.send_sms(to, content, reference, sender=sender)

    boto_mock.publish.assert_called_once_with(
        PhoneNumber=f"+1{to}",
        Message=content,
        MessageAttributes={
            'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': 'Transactional'},
            'AWS.MM.SMS.OriginationNumber': {'DataType': 'String', 'StringValue': sender},
        }
    )


def test_send_sms_to_us_number_successful_returns_aws_sns_response(notify_api, mocker):
    boto_mock = mocker.patch.object(aws_sns_client, '_long_codes_client', create=True)
    mocker.patch.object(aws_sns_client, 'statsd_client', create=True)

    us_toll_free_number = current_app.config["AWS_US_TOLL_FREE_NUMBER"]
    to = "7185555555"  # New York City Area Code
    content = reference = 'foo'

    with notify_api.app_context():
        aws_sns_client.send_sms(to, content, reference)

    boto_mock.publish.assert_called_once_with(
        PhoneNumber=f"+1{to}",
        Message=content,
        MessageAttributes={
            'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': 'Transactional'},
            'AWS.MM.SMS.OriginationNumber': {
                'DataType': 'String',
                'StringValue': us_toll_free_number,
            },
        }
    )


def test_send_sms_to_us_number_with_sender_successful_returns_aws_sns_response(notify_api, mocker):
    boto_mock = mocker.patch.object(aws_sns_client, '_long_codes_client', create=True)
    mocker.patch.object(aws_sns_client, 'statsd_client', create=True)

    sender = "+19025551234"
    us_toll_free_number = current_app.config["AWS_US_TOLL_FREE_NUMBER"]
    to = "7185555555"  # New York City Area Code
    content = reference = 'foo'

    with notify_api.app_context():
        aws_sns_client.send_sms(to, content, reference, sender=sender)

    boto_mock.publish.assert_called_once_with(
        PhoneNumber=f"+1{to}",
        Message=content,
        MessageAttributes={
            'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': 'Transactional'},
            'AWS.MM.SMS.OriginationNumber': {
                'DataType': 'String',
                'StringValue': us_toll_free_number,
            },
        }
    )
