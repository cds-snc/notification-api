from simple_salesforce.exceptions import SalesforceAuthenticationFailed

from app.clients.salesforce import salesforce_auth
from app.clients.salesforce.salesforce_auth import end_session, get_session


def test_get_session(mocker, notify_api):
    with notify_api.app_context():
        mock_salesforce = mocker.patch.object(salesforce_auth, "Salesforce", return_value="session")
        assert get_session("client_id", "username", "client_key", "privatekey", "domain") == mock_salesforce.return_value
        mock_salesforce.assert_called_with(
            client_id="client_id", username="username", consumer_key="client_key", privatekey="privatekey", domain="domain"
        )


def test_get_session_auth_failure(mocker, notify_api):
    with notify_api.app_context():
        mocker.patch.object(salesforce_auth, "Salesforce", side_effect=SalesforceAuthenticationFailed("aw", "dang"))
        assert get_session("client_id", "username", "client_key", "privatekey", "domain") is None


def test_end_session(mocker, notify_api):
    mock_session = mocker.MagicMock()
    mock_session.session_id = "session_id"
    with notify_api.app_context():
        end_session(mock_session)
        mock_session.oauth2.assert_called_with("revoke", {"token": mock_session.session_id}, method="POST")


def test_end_session_no_session(mocker, notify_api):
    mock_session = mocker.MagicMock()
    mock_session.session_id = None
    with notify_api.app_context():
        end_session(mock_session)
        mock_session.oauth2.assert_not_called()
