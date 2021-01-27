import re
from unittest.mock import ANY

import botocore
import pytest
from notifications_utils.recipients import InvalidEmailError

from app import aws_ses_client, config
from app.clients.email.aws_ses import (
    get_aws_responses,
    AwsSesClientException,
    AwsSesClient,
    AwsSesClientThrottlingSendRateException
)

ERROR_MESSAGE_FROM_AMAZON = 'some error message from amazon'
FROM_ADDRESS_COM = 'from@address.com'
FOO_BAR_COM = 'foo@bar.com'

STATSD_CLIENTS_SES_ERROR = "clients.ses.error"
STATSD_CLIENTS_SES_REQUEST_TIME = "clients.ses.request-time"


@pytest.fixture
def ses_client(mocker, client):
    mocker.patch.object(aws_ses_client, 'statsd_client', create=True)
    return aws_ses_client


@pytest.fixture
def boto_mock(ses_client, mocker):
    boto_mock = mocker.patch.object(ses_client, '_client', create=True)
    return boto_mock


def test_should_return_correct_details_for_delivery():
    response_dict = get_aws_responses('Delivery')
    assert response_dict['message'] == 'Delivered'
    assert response_dict['notification_status'] == 'delivered'
    assert response_dict['notification_statistics_status'] == 'delivered'
    assert response_dict['success']


def test_should_return_correct_details_for_hard_bounced():
    response_dict = get_aws_responses('Permanent')
    assert response_dict['message'] == 'Hard bounced'
    assert response_dict['notification_status'] == 'permanent-failure'
    assert response_dict['notification_statistics_status'] == 'failure'
    assert not response_dict['success']


def test_should_return_correct_details_for_soft_bounced():
    response_dict = get_aws_responses('Temporary')
    assert response_dict['message'] == 'Soft bounced'
    assert response_dict['notification_status'] == 'temporary-failure'
    assert response_dict['notification_statistics_status'] == 'failure'
    assert not response_dict['success']


def test_should_return_correct_details_for_complaint():
    response_dict = get_aws_responses('Complaint')
    assert response_dict['message'] == 'Complaint'
    assert response_dict['notification_status'] == 'delivered'
    assert response_dict['notification_statistics_status'] == 'delivered'
    assert response_dict['success']


def test_should_be_none_if_unrecognised_status_code():
    with pytest.raises(KeyError) as e:
        get_aws_responses('99')
    assert '99' in str(e.value)


@pytest.mark.parametrize('endpoint_url, expected', [
    (None, 'https://email.us-gov-west-1.amazonaws.com'),
    ('https://email-fips.us-gov-west-1.amazonaws.com', 'https://email-fips.us-gov-west-1.amazonaws.com')
],
    ids=['default_endpoint_for_region', 'custom_fips_endpoint'])
def test_should_use_correct_enpdoint_url_in_boto(endpoint_url, expected):
    local_aws_ses_client = AwsSesClient()
    local_aws_ses_client.init_app(
        config.Test.AWS_REGION,
        None,
        None,
        endpoint_url=endpoint_url)
    assert local_aws_ses_client._client._endpoint.host == expected


def test_should_use_enpdoint_from_config(notify_api):
    assert aws_ses_client._client._endpoint.host == config.Test.AWS_SES_ENDPOINT_URL


def test_send_email_uses_from_address(ses_client, boto_mock):
    ses_client.send_email(
        FROM_ADDRESS_COM,
        to_addresses=FOO_BAR_COM,
        subject='Subject',
        body='Body',
    )

    actual = boto_mock.send_raw_email.call_args[1]['Source']
    assert actual == FROM_ADDRESS_COM


def test_send_email_does_not_use_configuration_set_if_none(mocker):
    local_aws_ses_client = AwsSesClient()
    local_aws_ses_client.init_app(
        config.Test.AWS_REGION,
        mocker.Mock(),
        mocker.Mock(),
        configuration_set=None
    )
    boto_mock = mocker.patch.object(local_aws_ses_client, '_client', create=True)

    local_aws_ses_client.send_email(
        FROM_ADDRESS_COM,
        to_addresses=FOO_BAR_COM,
        subject='Subject',
        body='Body'
    )

    assert 'ConfigurationSetName' not in boto_mock.send_raw_email.call_args[1]


def test_send_email_uses_configuration_set_from_config(notify_api, ses_client, boto_mock):
    with notify_api.app_context():
        ses_client.send_email(
            FROM_ADDRESS_COM,
            to_addresses=FOO_BAR_COM,
            subject='Subject',
            body='Body',
        )

    actual = boto_mock.send_raw_email.call_args[1]['ConfigurationSetName']
    assert actual == config.Test.AWS_SES_CONFIGURATION_SET


@pytest.mark.parametrize('reply_to_address, expected_value', [
    (None, config.Test.AWS_SES_DEFAULT_REPLY_TO),
    (FOO_BAR_COM, FOO_BAR_COM)
], ids=['empty', 'single_email'])
def test_send_email_handles_reply_to_address(notify_api, ses_client, boto_mock, reply_to_address, expected_value):
    with notify_api.app_context():
        ses_client.send_email(
            source=FROM_ADDRESS_COM,
            to_addresses='to@address.com',
            subject='Subject',
            body='Body',
            reply_to_address=reply_to_address
        )

    raw_message = boto_mock.send_raw_email.call_args[1]['RawMessage']['Data']
    assert re.findall(r'reply-to: (.+@\w+.\w+)', raw_message)[0] == expected_value


def test_send_email_encodes_to_address(ses_client, boto_mock):
    ses_client.send_email(
        FROM_ADDRESS_COM,
        to_addresses='føøøø@bååååår.com',
        subject='Subject',
        body='Body',
    )

    raw_message = boto_mock.send_raw_email.call_args[1]['RawMessage']['Data']
    # When sending raw emails AWS SES required email addresses to be punycode and MIME encoded using following format:
    # =?charset?encoding?encoded-text?=
    assert re.findall(r'To: (=\?utf-8.*==\?=)\n',
                      raw_message)[0] == '=?utf-8?b?ZsO4w7jDuMO4QHhuLS1ici15aWFhYWFhLmNvbQ==?='
    ses_client.statsd_client.incr.assert_called_with("clients.ses.success")
    ses_client.statsd_client.timing.assert_called_with(STATSD_CLIENTS_SES_REQUEST_TIME, ANY)


def test_send_email_encodes_reply_to_address(ses_client, boto_mock):
    ses_client.send_email(
        FROM_ADDRESS_COM,
        to_addresses='to@address.com',
        subject='Subject',
        body='Body',
        reply_to_address='føøøø@bååååår.com'
    )

    raw_message = boto_mock.send_raw_email.call_args[1]['RawMessage']['Data']
    # When sending raw emails AWS SES required email addresses to be punycode and MIME encoded using following format:
    # =?charset?encoding?encoded-text?=
    assert re.findall(r'reply-to: (=\?utf-8.*==\?=)\n',
                      raw_message)[0] == '=?utf-8?b?ZsO4w7jDuMO4QHhuLS1ici15aWFhYWFhLmNvbQ==?='
    ses_client.statsd_client.incr.assert_called_with("clients.ses.success")
    ses_client.statsd_client.timing.assert_called_with(STATSD_CLIENTS_SES_REQUEST_TIME, ANY)


def test_send_email_raises_bad_email(ses_client, boto_mock):
    error_response = {
        'Error': {
            'Code': 'InvalidParameterValue',
            'Message': ERROR_MESSAGE_FROM_AMAZON,
            'Type': 'Sender'
        }
    }
    boto_mock.send_raw_email.side_effect = botocore.exceptions.ClientError(error_response, 'opname')

    with pytest.raises(InvalidEmailError) as excinfo:
        ses_client.send_email(
            source=FROM_ADDRESS_COM,
            to_addresses='definitely@invalid_email.com',
            subject='Subject',
            body='Body'
        )

    assert ERROR_MESSAGE_FROM_AMAZON in str(excinfo.value)
    assert 'definitely@invalid_email.com' in str(excinfo.value)
    ses_client.statsd_client.incr.assert_called_with("clients.ses.error.invalid-email")
    ses_client.statsd_client.timing.assert_called_with(STATSD_CLIENTS_SES_REQUEST_TIME, ANY)


def test_send_email_raises_other_errors(ses_client, boto_mock):
    error_response = {
        'Error': {
            'Code': 'ServiceUnavailable',
            'Message': ERROR_MESSAGE_FROM_AMAZON,
            'Type': 'Sender'
        }
    }
    boto_mock.send_raw_email.side_effect = botocore.exceptions.ClientError(error_response, 'opname')

    with pytest.raises(AwsSesClientException) as excinfo:
        ses_client.send_email(
            source=FROM_ADDRESS_COM,
            to_addresses=FOO_BAR_COM,
            subject='Subject',
            body='Body'
        )

    assert ERROR_MESSAGE_FROM_AMAZON in str(excinfo.value)
    ses_client.statsd_client.incr.assert_called_with(STATSD_CLIENTS_SES_ERROR)
    ses_client.statsd_client.timing.assert_called_with(STATSD_CLIENTS_SES_REQUEST_TIME, ANY)


def test_should_set_email_from_domain_when_it_is_overridden(client):
    assert aws_ses_client.email_from_domain == config.Test.AWS_SES_EMAIL_FROM_DOMAIN


def test_should_set_email_from_user_when_it_is_overridden(client):
    assert aws_ses_client.email_from_user == config.Test.AWS_SES_EMAIL_FROM_USER


def test_send_email_raises_send_rate_throttling_exception(client, ses_client, boto_mock):
    error_response = {
        'Error': {
            'Code': 'Throttling',
            'Message': 'Maximum sending rate exceeded.',
            'Type': 'Sender'
        }
    }
    boto_mock.send_raw_email.side_effect = botocore.exceptions.ClientError(error_response, 'opname')

    with pytest.raises(AwsSesClientThrottlingSendRateException):
        ses_client.send_email(
            source=FROM_ADDRESS_COM,
            to_addresses=FOO_BAR_COM,
            subject='Subject',
            body='Body'
        )

    ses_client.statsd_client.incr.assert_called_with("clients.ses.error.throttling")
    ses_client.statsd_client.timing.assert_called_with(STATSD_CLIENTS_SES_REQUEST_TIME, ANY)


def test_send_email_does_not_raise_exception_if_non_send_rate_throttling(ses_client, boto_mock):
    error_response = {
        'Error': {
            'Code': 'Throttling',
            'Message': 'Daily message quota exceeded',
            'Type': 'Sender'
        }
    }
    boto_mock.send_raw_email.side_effect = botocore.exceptions.ClientError(error_response, 'opname')

    with pytest.raises(AwsSesClientException):
        ses_client.send_email(
            source=FROM_ADDRESS_COM,
            to_addresses=FOO_BAR_COM,
            subject='Subject',
            body='Body'
        )
    ses_client.statsd_client.incr.assert_called_with(STATSD_CLIENTS_SES_ERROR)
    ses_client.statsd_client.timing.assert_called_with(STATSD_CLIENTS_SES_REQUEST_TIME, ANY)


def test_send_email_does_not_call_statsd_if_boto_is_not_called(client, mocker, ses_client):

    with pytest.raises(Exception):
        ses_client.send_email(
            source=None,
            to_addresses=FOO_BAR_COM,
            subject='Subject',
            body='Body'
        )

    ses_client.statsd_client.incr.assert_not_called()
    ses_client.statsd_client.timing.assert_not_called()
