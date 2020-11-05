from app import aws_sns_client


def test_send_sms_successful_returns_aws_sns_response(notify_api, mocker):
    boto_mock = mocker.patch.object(aws_sns_client, '_client', create=True)
    mocker.patch.object(aws_sns_client, 'statsd_client', create=True)
    boto_mock.publish.return_value = {'MessageId': 'some-identifier'}

    to = "+16135555555"
    content = reference = 'foo'

    with notify_api.app_context():
        response = aws_sns_client.send_sms(to, content, reference)

    boto_mock.publish.assert_called_once_with(
        PhoneNumber="+16135555555",
        Message=content,
        MessageAttributes={'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': 'Transactional'}}
    )

    assert response == 'some-identifier'
