import uuid

from flask import current_app
from notifications_python_client.authentication import create_jwt_token

from app.dao.api_key_dao import save_model_api_key
from app.dao.services_dao import dao_fetch_service_by_id
from app.models import KEY_TYPE_NORMAL, ApiKey


def create_authorization_header(service_id=None, key_type=KEY_TYPE_NORMAL, api_key_required=False):
    if service_id:
        client_id = str(service_id)
        api_keys = ApiKey.query.filter_by(service_id=service_id, key_type=key_type).all()
        if api_keys:
            api_key = api_keys[0]
        else:
            service = dao_fetch_service_by_id(service_id)
            data = {
                "service": service,
                "name": uuid.uuid4(),
                "created_by": service.created_by,
                "key_type": key_type,
            }
            api_key = ApiKey(**data)
            save_model_api_key(api_key)
        secret = api_key.secret
    else:
        client_id = current_app.config["ADMIN_CLIENT_USER_NAME"]
        secret = current_app.config["ADMIN_CLIENT_SECRET"]

    token = create_jwt_token(secret=secret, client_id=client_id)

    if service_id and api_key_required:
        return (("Authorization", "Bearer {}".format(token)), api_key)
    else:
        return "Authorization", "Bearer {}".format(token)


def unwrap_function(fn):
    """
    Given a function, returns its undecorated original.
    """
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn
