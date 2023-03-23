import pytest

from app.clients.salesforce import salesforce_auth, salesforce_contact
from app.clients.salesforce.salesforce_client import SalesforceClient


@pytest.fixture(scope="function")
def salesforce_client(client, mocker):
    client = SalesforceClient()
    current_app = mocker.Mock(
        config={
            "SALESFORCE_CLIENT_ID": "Notify",
            "SALESFORCE_USERNAME": "someusername",
            "SALESFORCE_CLIENT_KEY": "client_key",
            "SALESFORCE_CLIENT_PRIVATEKEY": "cHJpdmF0ZWtleQo=",
            "SALESFORCE_DOMAIN": "test",
        }
    )
    client.init_app(current_app)
    return client


def test_get_session(mocker, salesforce_client):
    mock_get_session = mocker.patch.object(salesforce_auth, "get_session", return_value="session")
    assert salesforce_client.get_session() == mock_get_session.return_value
    mock_get_session.assert_called_once_with("Notify", "someusername", "client_key", b"privatekey\n", "test")


def test_end_session(mocker, salesforce_client):
    mock_end_session = mocker.patch.object(salesforce_auth, "end_session", return_value="session")
    salesforce_client.end_session("session")
    mock_end_session.assert_called_once_with("session")


def test_contact_create(mocker, salesforce_client):
    mock_get_session = mocker.patch.object(salesforce_client, "get_session", return_value="session")
    mock_create = mocker.patch.object(salesforce_contact, "create")
    mock_end_session = mocker.patch.object(salesforce_client, "end_session")

    salesforce_client.contact_create("user", "account_id")

    mock_get_session.assert_called_once()
    mock_create.assert_called_once_with("session", "user", "account_id")
    mock_end_session.assert_called_once_with("session")
