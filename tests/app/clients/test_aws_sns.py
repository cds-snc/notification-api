import pytest
from app.clients.sms.aws_sns import AwsSnsClient


@pytest.fixture(scope='function')
def aws_sns_client(mocker):
    aws_sns_client = AwsSnsClient()
    statsd_client = mocker.Mock()
    logger = mocker.Mock()
    aws_sns_client.init_app('some-aws-region', statsd_client, logger)
    return aws_sns_client


@pytest.fixture(scope='function')
def boto_mock(aws_sns_client, mocker):
    boto_mock = mocker.patch.object(aws_sns_client, '_client', create=True)
    return boto_mock


def test_send_sms_successful_returns_aws_sns_response(aws_sns_client, boto_mock):
    boto_mock.publish.return_value = {'MessageId': 'some-identifier'}

    to = '+16135555555'
    content = reference = 'foo'

    response = aws_sns_client.send_sms(to, content, reference)

    boto_mock.publish.assert_called_once_with(
        PhoneNumber='+16135555555',
        Message=content,
        MessageAttributes={'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': 'Transactional'}},
    )

    assert response == 'some-identifier'
