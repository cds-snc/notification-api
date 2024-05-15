from typing import Optional
import requests
from flask import current_app
from simple_salesforce import Salesforce

SALESFORCE_TIMEOUT_SECONDS = 3


class TimeoutAdapter(requests.adapters.HTTPAdapter):
    """Custom adapter to add a timeout to Salesforce API requests"""

    def send(self, *args, **kwargs):
        kwargs["timeout"] = SALESFORCE_TIMEOUT_SECONDS
        return super().send(*args, **kwargs)


def get_session(client_id: str, username: str, password: str, security_token: str, domain: str) -> Optional[Salesforce]:
    """Return an authenticated Salesforce session

    Args:
        client_id (str): The name of the Salesforce connected app.
        username (str): The username to use for authentication.  This users permissions will be used for the session.
        password (str): The password of the user that is authenticating.
        security_token (str): The security token of the user that is authenticating.
        domain (str): The domain of the Salesforce instance.  Use `test` for the QA instance.

    Returns:
        Salesforce: the authenticated Salesforce session.
    """
    session = None
    try:
        # Add a timeout to Salesforce API requests
        requests_session = requests.Session()
        requests_session.mount("https://", TimeoutAdapter())
        requests_session.mount("http://", TimeoutAdapter())

        session = Salesforce(
            client_id=client_id,
            username=username,
            password=password,
            security_token=security_token,
            domain=domain,
            session=requests_session,
        )
    except Exception as ex:
        current_app.logger.error(f"SF_ERR Salesforce login failed: {ex}")
    return session


def end_session(session: Optional[Salesforce]):
    """Logout of a Salesforce session

    Args:
        session (Salesforce): The session to revoke.
    """
    try:
        if session and session.session_id:
            session.oauth2("revoke", {"token": session.session_id}, method="POST")
    except Exception as ex:
        current_app.logger.error(f"SF_ERR Salesforce logout failed: {ex}")
