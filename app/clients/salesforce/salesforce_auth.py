from flask import current_app
from simple_salesforce import Salesforce


def get_session(client_id, username, consumer_key, privatekey, domain) -> Salesforce:
    """Return an authenticated Salesforce session

    Args:
        client (SalesforceClient): The Salesforce client being used for the request.

    Returns:
        Salesforce: the authenticated Salesforce session.
    """
    session = None
    try:
        session = Salesforce(
            client_id=client_id,
            username=username,
            consumer_key=consumer_key,
            privatekey=privatekey,
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
