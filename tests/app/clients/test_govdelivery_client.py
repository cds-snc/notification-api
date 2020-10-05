from unittest.mock import ANY

import pytest
import requests
import requests_mock
from notifications_utils.recipients import InvalidEmailError

from app.clients.email.govdelivery_client import GovdeliveryClient, GovdeliveryClientException, \
    map_govdelivery_status_to_notify_status
from app.models import NOTIFICATION_SENDING, NOTIFICATION_SENT, NOTIFICATION_CANCELLED, NOTIFICATION_FAILED, \
    NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_PENDING


@pytest.fixture(scope='function')
def client(notify_api, mocker):
    with notify_api.app_context():
        govdelivery_client = GovdeliveryClient()
        statsd_client = mocker.Mock()
        govdelivery_client.init_app("some-token", "https://govdelivery-url", statsd_client)
        return govdelivery_client


@pytest.fixture(scope='function')
def respond_successfully():
    rmock = requests_mock.mock()
    rmock.post(
        requests_mock.ANY,
        json={
            "id": 1234
        }
    )
    return rmock


def test_should_get_name(client):
    assert client.get_name() == "govdelivery"


def test_send_email_posts_to_correct_url(client, respond_successfully):
    with respond_successfully:
        client.send_email("source", "address", "subject", "body", "html body")

    expected_govdelivery_url = "https://govdelivery-url/messages/email"

    assert respond_successfully.request_history[0].url == expected_govdelivery_url


def test_token_appears_as_header_in_request(client, respond_successfully):
    token = "some-token"
    client.token = token

    with respond_successfully:
        client.send_email("source", "address", "subject", "body", "html body")

    assert respond_successfully.request_history[0].headers["X-AUTH-TOKEN"] == token


def test_send_email_has_correct_payload_and_uses_html_body(client, respond_successfully):
    subject = "some subject"
    body = "some body"
    html_body = "some html body"
    recipient = "recipient@email.com"
    sender = "sender@email.com"

    with respond_successfully:
        client.send_email(sender, recipient, subject, body, html_body)

    expected_payload = {
        "subject": subject,
        "body": html_body,
        "recipients": [
            {
                "email": recipient
            }
        ],
        "from_email": sender,
        "click_tracking_enabled": False
    }

    assert respond_successfully.request_history[0].json() == expected_payload


def test_send_email_with_multiple_recipients(client, respond_successfully):
    recipient_emails = ["recipient1@email.com", "recipient2@email.com", "recipient3@email.com"]

    with respond_successfully:
        client.send_email("source", recipient_emails, "subject", "body", "html body")

    json = respond_successfully.request_history[0].json()

    assert len(json["recipients"]) == 3
    assert json["recipients"][0]["email"] == recipient_emails[0]
    assert json["recipients"][1]["email"] == recipient_emails[1]
    assert json["recipients"][2]["email"] == recipient_emails[2]


def test_from_email_is_only_email_when_name_also_provided(client, respond_successfully):
    source = '"Sender Name" <sender@email.com>'
    with respond_successfully:
        client.send_email(source, "recipient@email.com", "subject", "body", "html body")

    assert respond_successfully.request_history[0].json()["from_email"] == "sender@email.com"


def test_should_raise_http_errors_as_govdelivery_client_exception(client):
    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY,
            status_code=500
        )
        with pytest.raises(GovdeliveryClientException):
            client.send_email("source", "recipient@email.com", "subject", "body", "html body")
    client.statsd_client.incr.assert_called_with("clients.govdelivery.error")


def test_should_raise_connection_errors_as_govdelivery_client_exception(client):
    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY,
            exc=requests.exceptions.ConnectionError
        )
        with pytest.raises(GovdeliveryClientException):
            client.send_email("source", "recipient@email.com", "subject", "body", "html body")
    client.statsd_client.incr.assert_called_with("clients.govdelivery.error")


def test_should_raise_422_as_invalid_email_exception(client):
    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY,
            status_code=422
        )
        with pytest.raises(InvalidEmailError):
            client.send_email("source", "recipient@email.com", "subject", "body", "html body")
    client.statsd_client.incr.assert_called_with("clients.govdelivery.error")


def test_should_time_request_and_increment_success_count(client, respond_successfully):
    with respond_successfully:
        client.send_email("source", "recipient@email.com", "subject", "body", "html body")

    client.statsd_client.timing.assert_called_with("clients.govdelivery.request-time", ANY)
    client.statsd_client.incr.assert_called_with("clients.govdelivery.success")


def test_should_return_message_id(client):
    message_id = 5678
    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY,
            json={
                "id": message_id
            }
        )
        response = client.send_email("source", "recipient@email.com", "subject", "body", "html body")

    assert response == message_id


@pytest.mark.parametrize('govdelivery_status, notify_status', [
    ('sending', NOTIFICATION_SENDING),
    ('sent', NOTIFICATION_SENT),
    ('blacklisted', NOTIFICATION_PERMANENT_FAILURE),
    ('canceled', NOTIFICATION_CANCELLED),
    ('failed', NOTIFICATION_FAILED),
    ('inconclusive', NOTIFICATION_PENDING)
])
def test_should_map_status(govdelivery_status, notify_status):
    assert map_govdelivery_status_to_notify_status(govdelivery_status) == notify_status
