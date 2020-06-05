import pytest

from app import send_grid_client
from app.clients.email.sendgrid_client import get_sendgrid_responses, SendGridClientException


def test_should_return_correct_response_details():
    assert get_sendgrid_responses('processed') == "created"
    assert get_sendgrid_responses('deferred') == "deferred"
    assert get_sendgrid_responses('delivered') == "sent"
    assert get_sendgrid_responses('bounce') == "permanent-failure"
    assert get_sendgrid_responses('dropped') == "technical-failure"


@pytest.mark.parametrize('reply_to_address, expected_value', [
    (None, []),
    ('foo@bar.com', ['foo@bar.com']),
    ('føøøø@bååååår.com', ['føøøø@xn--br-yiaaaaa.com'])
], ids=['empty', 'single_email', 'punycode'])
def test_send_email_handles_reply_to_address(notify_api, mocker, reply_to_address, expected_value):
    sendgrid_mock = mocker.patch.object(send_grid_client, '_client', create=True)
    mocker.patch.object(send_grid_client, 'statsd_client', create=True)

    with notify_api.app_context():
        send_grid_client.send_email(
            source='from@address.com',
            to_addresses='to@address.com',
            subject='Subject',
            body='Body',
            reply_to_address=reply_to_address
        )

    sendgrid_mock.client.mail.send.post.assert_called()


def test_send_email_handles_punycode_to_address(notify_api, mocker):
    sendgrid_mock = mocker.patch.object(send_grid_client, '_client', create=True)
    mocker.patch.object(send_grid_client, 'statsd_client', create=True)

    with notify_api.app_context():
        send_grid_client.send_email(
            'from@address.com',
            to_addresses='føøøø@bååååår.com',
            subject='Subject',
            body='Body',
        )

    sendgrid_mock.client.mail.send.post.assert_called()


def test_send_email_raises_bad_email_as_SendGridClientException(mocker):
    sendgrid_mock = mocker.patch.object(send_grid_client, '_client', create=True)
    mocker.patch.object(send_grid_client, 'statsd_client', create=True)
    sendgrid_mock.client.mail.send.post.side_effect = SendGridClientException
    with pytest.raises(SendGridClientException):
        send_grid_client.send_email(
            source='from@address.com',
            to_addresses=None,
            subject='Subject',
            body='Body'
        )
