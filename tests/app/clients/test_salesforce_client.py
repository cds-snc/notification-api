import pytest

from app.clients.salesforce import (
    salesforce_account,
    salesforce_auth,
    salesforce_contact,
    salesforce_engagement,
)
from app.clients.salesforce.salesforce_client import SalesforceClient


@pytest.fixture(scope="function")
def salesforce_client(client, mocker):
    client = SalesforceClient()
    current_app = mocker.Mock(
        config={
            "SALESFORCE_CLIENT_ID": "Notify",
            "SALESFORCE_USERNAME": "someusername",
            "SALESFORCE_PASSWORD": "somepassword",
            "SALESFORCE_SECURITY_TOKEN": "somesecuritytoken",
            "SALESFORCE_DOMAIN": "test",
            "SALESFORCE_GENERIC_ACCOUNT_ID": "someaccountid",
        }
    )
    client.init_app(current_app)
    return client


def test_get_session(mocker, salesforce_client):
    mock_get_session = mocker.patch.object(salesforce_auth, "get_session", return_value="session")
    assert salesforce_client.get_session() == mock_get_session.return_value
    mock_get_session.assert_called_once_with("Notify", "someusername", "somepassword", "somesecuritytoken", "test")


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


def test_contact_update_account_id(mocker, salesforce_client):
    mock_get_account_name_from_org = mocker.patch.object(
        salesforce_account, "get_org_name_from_notes", return_value="account_name"
    )
    mock_get_account_id_from_name = mocker.patch.object(salesforce_account, "get_account_id_from_name", return_value="account_id")
    mock_update_account_id = mocker.patch.object(salesforce_contact, "update_account_id", return_value="contact_id")
    mock_session = mocker.MagicMock()
    mock_service = mocker.MagicMock()
    mock_service.organisation_notes = "account_name > service_name"

    salesforce_client.contact_update_account_id(mock_session, mock_service, "user")

    mock_get_account_name_from_org.assert_called_once_with(mock_service.organisation_notes)
    mock_get_account_id_from_name.assert_called_once_with(mock_session, "account_name", "someaccountid")
    mock_update_account_id.assert_called_once_with(mock_session, "user", "account_id")


def test_engagement_create(mocker, salesforce_client):
    mock_get_session = mocker.patch.object(salesforce_client, "get_session", return_value="session")
    mock_contact_update_account_id = mocker.patch.object(
        salesforce_client, "contact_update_account_id", return_value=("account_id", "contact_id")
    )
    mock_create = mocker.patch.object(salesforce_engagement, "create")
    mock_end_session = mocker.patch.object(salesforce_client, "end_session")
    mock_service = mocker.MagicMock()
    mock_service.organisation_notes = "account_name > service_name"

    salesforce_client.engagement_create(mock_service, "user")

    mock_get_session.assert_called_once()
    mock_contact_update_account_id.assert_called_once_with("session", mock_service, "user")
    mock_create.assert_called_once_with("session", mock_service, {}, "account_id", "contact_id")
    mock_end_session.assert_called_once_with("session")


def test_engagement_update_stage(mocker, salesforce_client):
    mock_get_session = mocker.patch.object(salesforce_client, "get_session", return_value="session")
    mock_contact_update_account_id = mocker.patch.object(
        salesforce_client, "contact_update_account_id", return_value=("account_id", "contact_id")
    )
    mock_update = mocker.patch.object(salesforce_engagement, "update")
    mock_end_session = mocker.patch.object(salesforce_client, "end_session")
    mock_service = mocker.MagicMock()
    mock_service.organisation_notes = "account_name > service_name"

    salesforce_client.engagement_update_stage(mock_service, "user", "live")

    mock_get_session.assert_called_once()
    mock_contact_update_account_id.assert_called_once_with("session", mock_service, "user")
    mock_update.assert_called_once_with("session", mock_service, {"StageName": "live"}, "account_id", "contact_id")
    mock_end_session.assert_called_once_with("session")


def test_engagement_close(mocker, salesforce_client):
    mock_get_session = mocker.patch.object(salesforce_client, "get_session", return_value="session")
    mock_get_engagement_by_service_id = mocker.patch.object(
        salesforce_engagement, "get_engagement_by_service_id", return_value="engagement_id"
    )
    mock_update = mocker.patch.object(salesforce_engagement, "update")
    mock_end_session = mocker.patch.object(salesforce_client, "end_session")
    mock_service = mocker.MagicMock()
    mock_service.id = "service_id"

    salesforce_client.engagement_close(mock_service)

    mock_get_session.assert_called_once()
    mock_get_engagement_by_service_id.assert_called_once_with("session", mock_service.id)
    mock_update.assert_called_once_with(
        "session", mock_service, {"CDS_Close_Reason__c": "Trial deleted by user", "StageName": "Closed"}, None, None
    )
    mock_end_session.assert_called_once_with("session")


def test_engagement_close_no_engagement(mocker, salesforce_client):
    mock_get_session = mocker.patch.object(salesforce_client, "get_session", return_value="session")
    mock_get_engagement_by_service_id = mocker.patch.object(
        salesforce_engagement, "get_engagement_by_service_id", return_value=None
    )
    mock_update = mocker.patch.object(salesforce_engagement, "update")
    mock_end_session = mocker.patch.object(salesforce_client, "end_session")
    mock_service = mocker.MagicMock()
    mock_service.id = "service_id"

    salesforce_client.engagement_close(mock_service)

    mock_get_session.assert_called_once()
    mock_get_engagement_by_service_id.assert_called_once_with("session", mock_service.id)
    mock_update.assert_not_called()
    mock_end_session.assert_called_once_with("session")
