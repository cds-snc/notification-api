from flask import current_app
from simple_salesforce import Salesforce


def get_session(client_id: str, username: str, password: str, security_token: str, domain: str) -> Salesforce:
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
        session = Salesforce(
            client_id=client_id,
            username=username,
            password=password,
            security_token=security_token,
            domain=domain,
        )
    except Exception as ex:
        current_app.logger.error(f"Salesforce login failed: {ex}")
    return session


def end_session(session: Salesforce):
    """Logout of a Salesforce session

    Args:
        session (Salesforce): The session to revoke.
    """
    try:
        if session and session.session_id:
            session.oauth2("revoke", {"token": session.session_id}, method="POST")
    except Exception as ex:
        current_app.logger.error(f"Salesforce logout failed: {ex}")
