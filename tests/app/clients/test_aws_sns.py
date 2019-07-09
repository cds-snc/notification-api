import pytest
from app import aws_sns_client


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
