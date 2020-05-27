import pytest
import requests_mock

from app.clients.email.govdelivery_client import GovdeliveryClient


@pytest.fixture(scope='function')
def client(mocker):
    govdelivery_client = GovdeliveryClient()
    statsd_client = mocker.Mock()
    govdelivery_client.init_app(statsd_client)
    return govdelivery_client


def test_should_get_name(client):
    assert client.get_name() == "govdelivery"


def test_send_email(client):
    expected_govdelivery_url = "https://tms.govdelivery.com/messages/email"
    with requests_mock.mock() as rmock:
        rmock.post(
            requests_mock.ANY
        )
        client.send_email("source", "address", "subject", "body")

    assert rmock.request_history[0].url == expected_govdelivery_url