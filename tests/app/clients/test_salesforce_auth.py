from unittest.mock import call

from simple_salesforce.exceptions import SalesforceAuthenticationFailed

from app.clients.salesforce import salesforce_auth
from app.clients.salesforce.salesforce_auth import end_session, get_session


def test_get_session(mocker, notify_api):
    with notify_api.app_context():
        mock_salesforce = mocker.patch.object(salesforce_auth, "Salesforce", return_value="session")
        mock_timeout_adapter = mocker.patch.object(salesforce_auth, "TimeoutAdapter", return_value="timeout_adapter")
        mock_requests = mocker.patch.object(salesforce_auth, "requests")
        mock_requests.Session.return_value = mocker.MagicMock()
        assert get_session("client_id", "username", "password", "security_token", "domain") == mock_salesforce.return_value
        mock_salesforce.assert_called_with(
            client_id="client_id",
            username="username",
            password="password",
            security_token="security_token",
            domain="domain",
            session=mock_requests.Session.return_value,
        )
        mock_requests.Session.return_value.mount.assert_has_calls(
            [call("https://", mock_timeout_adapter.return_value), call("http://", mock_timeout_adapter.return_value)]
        )


def test_get_session_auth_failure(mocker, notify_api):
    with notify_api.app_context():
        mocker.patch.object(salesforce_auth, "Salesforce", side_effect=SalesforceAuthenticationFailed("aw", "dang"))
        assert get_session("client_id", "username", "password", "security_token", "domain") is None


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
