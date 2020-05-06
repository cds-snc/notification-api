import pytest
from app import aws_pinpoint_client
from flask import current_app


def test_send_sms_successful_returns_aws_pinpoint_response(notify_api, mocker):
    boto_mock = mocker.patch.object(aws_pinpoint_client, '_client', create=True)
    mocker.patch.object(aws_pinpoint_client, 'statsd_client', create=True)

    to = "6135555555"
    content = reference = 'foo'
    sender = "+12345678901"

    with notify_api.app_context():
        aws_pinpoint_client.send_sms(to, content, reference, True, sender)

    boto_mock.send_messages.assert_called_once_with(
        ApplicationId=current_app.config['AWS_PINPOINT_APP_ID'],
        MessageRequest={
            'Addresses': {
                "+16135555555": {
                    'ChannelType': 'SMS'
                }
            },
            'MessageConfiguration': {
                'SMSMessage': {
                    'Body': content,
                    'Keyword': current_app.config['AWS_PINPOINT_KEYWORD'],
                    'MessageType': "TRANSACTIONAL",
                    'OriginationNumber': sender
                }
            }
        }
    )


def test_send_sms_returns_raises_error_if_there_is_no_valid_number_is_found(notify_api, mocker):
    mocker.patch.object(aws_pinpoint_client, '_client', create=True)
    mocker.patch.object(aws_pinpoint_client, 'statsd_client', create=True)

    to = ""
    content = reference = 'foo'

    with pytest.raises(ValueError) as excinfo:
        aws_pinpoint_client.send_sms(to, content, reference)

    assert 'No valid numbers found for SMS delivery' in str(excinfo.value)
