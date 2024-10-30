from flask import current_app
from notifications_python_client.authentication import create_jwt_token

from app.models import ApiKey


def create_admin_authorization_header() -> str:
    """
    Creates an admin auth header
    """

    client_id = current_app.config['ADMIN_CLIENT_USER_NAME']
    secret = current_app.config['ADMIN_CLIENT_SECRET']
    token = create_jwt_token(secret=secret, client_id=client_id)
    return 'Authorization', f'Bearer {token}'


def create_authorization_header(api_key: ApiKey) -> str:
    """
    Takes an API key and returns an authorization header. Utilizes the service FK.
    """

    token = create_jwt_token(secret=api_key.secret, client_id=str(api_key.service_id))
    return 'Authorization', f'Bearer {token}'


def unwrap_function(fn):
    """
    Given a function, returns its undecorated original.
    """

    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    return fn
