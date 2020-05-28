import pytest
import requests
import requests_mock
from notifications_utils.recipients import InvalidEmailError

from app.clients.email.govdelivery_client import GovdeliveryClient, GovdeliveryClientException


@pytest.fixture(scope='function')
def client(mocker):
    govdelivery_client = GovdeliveryClient()
    statsd_client = mocker.Mock()
    govdelivery_client.init_app("some-token", statsd_client)
    return govdelivery_client


def test_should_get_name(client):
    assert client.get_name() == "govdelivery"


def test_send_email_posts_to_correct_url(client):
    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY
        )
        client.send_email("source", "address", "subject", "body")

    expected_govdelivery_url = "https://tms.govdelivery.com/messages/email"

    assert rmock.request_history[0].url == expected_govdelivery_url


def test_token_appears_as_header_in_request(mocker):
    token = "some-token"
    client = GovdeliveryClient()
    client.init_app(token, mocker.Mock())

    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY
        )
        client.send_email("source", "address", "subject", "body")

    assert rmock.request_history[0].headers["X-AUTH-TOKEN"] == token


def test_send_email_has_correct_payload(client):
    subject = "some subject"
    body = "some body"
    recipient = "recipient@email.com"
    sender = "sender@email.com"

    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY
        )
        client.send_email(sender, recipient, subject, body)

    expected_payload = {
        "subject": subject,
        "body": body,
        "recipients": [
            {
                "email": recipient
            }
        ],
        "from_email": sender
    }

    assert rmock.request_history[0].json() == expected_payload


def test_send_email_with_multiple_recipients(client):
    recipient_emails = ["recipient1@email.com", "recipient2@email.com", "recipient3@email.com"]

    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY
        )
        client.send_email("source", recipient_emails, "subject", "body")

    json = rmock.request_history[0].json()

    assert len(json["recipients"]) == 3
    assert json["recipients"][0]["email"] == recipient_emails[0]
    assert json["recipients"][1]["email"] == recipient_emails[1]
    assert json["recipients"][2]["email"] == recipient_emails[2]


def test_from_email_is_only_email_when_name_also_provided(client):
    source = '"Sender Name" <sender@email.com>'
    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY
        )
        client.send_email(source, "recipient@email.com", "subject", "body")

    assert rmock.request_history[0].json()["from_email"] == "sender@email.com"


def test_should_raise_http_errors_as_govdelivery_client_exception(client):
    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY,
            status_code=500
        )
        with pytest.raises(GovdeliveryClientException):
            client.send_email("source", "recipient@email.com", "subject", "body")


def test_should_raise_connection_errors_as_govdelivery_client_exception(client):
    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY,
            exc=requests.exceptions.ConnectionError
        )
        with pytest.raises(GovdeliveryClientException):
            client.send_email("source", "recipient@email.com", "subject", "body")


def test_should_raise_422_as_invalid_email_exception(client):
    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY,
            status_code=422
        )
        with pytest.raises(InvalidEmailError):
            client.send_email("source", "recipient@email.com", "subject", "body")
