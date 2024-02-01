from flask import current_app, g, request  # type: ignore
from jwt import PyJWTError
from notifications_python_client.authentication import (
    decode_jwt_token,
    decode_token,
    epoch_seconds,
    get_token_issuer,
)
from notifications_python_client.errors import (
    TokenDecodeError,
    TokenExpiredError,
    TokenIssuerError,
)
from notifications_utils import request_helper
from sqlalchemy.exc import DataError
from sqlalchemy.orm.exc import NoResultFound

from app.dao.api_key_dao import get_api_key_by_secret
from app.dao.services_dao import dao_fetch_service_by_id_with_api_keys

JWT_AUTH_TYPE = "jwt"
API_KEY_V1_AUTH_TYPE = "api_key_v1"
AUTH_TYPES = [
    (
        "Bearer",
        JWT_AUTH_TYPE,
        "JWT token that the client generates and passes in, "
        "Learn more: https://documentation.notification.canada.ca/en/start.html#headers.",
    ),
    (
        "ApiKey-v1",
        API_KEY_V1_AUTH_TYPE,
        "If you cannot generate a JWT token you may optionally use "
        "the API secret generated for you by GC Notify. "
        "Learn more: https://documentation.notification.canada.ca/en/start.html#headers.",
    ),
]


class AuthError(Exception):
    def __init__(self, message, code, service_id=None, api_key_id=None):
        self.message = {"token": [message]}
        self.short_message = message
        self.code = code
        self.service_id = service_id
        self.api_key_id = api_key_id

    def __str__(self):
        return "AuthError({message}, {code}, service_id={service_id}, api_key_id={api_key_id})".format(**self.__dict__)

    def to_dict_v2(self):
        return {
            "status_code": self.code,
            "errors": [{"error": "AuthError", "message": self.short_message}],
        }


def get_auth_token(req):
    auth_header = req.headers.get("Authorization", None)
    if not auth_header:
        raise AuthError("Unauthorized, authentication token must be provided", 401)

    for el in AUTH_TYPES:
        scheme, auth_type, _ = el
        if auth_header.lower().startswith(scheme.lower()):
            token = auth_header[len(scheme) + 1 :]
            return auth_type, token

    raise AuthError(
        "Unauthorized, Authorization header is invalid. "
        "GC Notify supports the following authentication methods. "
        + ", ".join([f"{auth_type[0]}: {auth_type[2]}" for auth_type in AUTH_TYPES]),
        401,
    )


def requires_no_auth():
    pass


def requires_admin_auth():
    request_helper.check_proxy_header_before_request()

    auth_type, auth_token = get_auth_token(request)
    if auth_type != JWT_AUTH_TYPE:
        raise AuthError("Invalid scheme: can only use JWT for admin authentication", 401)
    client = __get_token_issuer(auth_token)

    if client == current_app.config.get("ADMIN_CLIENT_USER_NAME"):
        g.service_id = current_app.config.get("ADMIN_CLIENT_USER_NAME")
        return handle_admin_key(auth_token, current_app.config.get("ADMIN_CLIENT_SECRET"))
    else:
        raise AuthError("Unauthorized, admin authentication token required", 401)


def requires_sre_auth():
    request_helper.check_proxy_header_before_request()

    auth_type, auth_token = get_auth_token(request)
    if auth_type != JWT_AUTH_TYPE:
        raise AuthError("Invalid scheme: can only use JWT for sre authentication", 401)
    client = __get_token_issuer(auth_token)

    if client == current_app.config.get("SRE_USER_NAME"):
        g.service_id = current_app.config.get("SRE_USER_NAME")
        return handle_admin_key(auth_token, current_app.config.get("SRE_CLIENT_SECRET"))
    else:
        raise AuthError("Unauthorized, sre authentication token required", 401)


def requires_auth():
    request_helper.check_proxy_header_before_request()

    auth_type, auth_token = get_auth_token(request)
    if auth_type == API_KEY_V1_AUTH_TYPE:
        _auth_by_api_key(auth_token)
        return
    client = __get_token_issuer(auth_token)

    try:
        service = dao_fetch_service_by_id_with_api_keys(client)
    except DataError:
        raise AuthError("Invalid token: service id is not the right data type", 403)
    except NoResultFound:
        raise AuthError("Invalid token: service not found", 403)

    if not service.api_keys:
        raise AuthError("Invalid token: service has no API keys", 403, service_id=service.id)

    if not service.active:
        raise AuthError("Invalid token: service is archived", 403, service_id=service.id)

    for api_key in service.api_keys:
        try:
            decode_jwt_token(auth_token, api_key.secret)
        except TokenDecodeError:
            continue
        except TokenExpiredError:
            try:
                decoded_token = decode_token(auth_token)
            except PyJWTError:
                continue
            current_app.logger.info(f'JWT: iat value was {decoded_token["iat"]} while server clock is {epoch_seconds()}')
            err_msg = "Error: Your system clock must be accurate to within 30 seconds"
            raise AuthError(err_msg, 403, service_id=service.id, api_key_id=api_key.id)

        _auth_with_api_key(api_key, service)
        return
    else:
        # service has API keys, but none matching the one the user provided
        raise AuthError("Invalid token: signature, api token not found", 403, service_id=service.id)


def _auth_by_api_key(auth_token):
    try:
        api_key = get_api_key_by_secret(auth_token)
    except NoResultFound:
        raise AuthError("Invalid token: API key not found", 403)
    _auth_with_api_key(api_key, api_key.service)


def _auth_with_api_key(api_key, service):
    if api_key.expiry_date:
        raise AuthError(
            "Invalid token: API key revoked",
            403,
            service_id=service.id,
            api_key_id=api_key.id,
        )

    g.service_id = api_key.service_id
    g.authenticated_service = service
    g.api_user = api_key
    current_app.logger.info(
        "API authorised for service {} with api key {}, using client {}".format(
            service.id, api_key.id, request.headers.get("User-Agent")
        )
    )


def __get_token_issuer(auth_token):
    try:
        client = get_token_issuer(auth_token)
    except TokenIssuerError:
        raise AuthError("Invalid token: iss field not provided", 403)
    except TokenDecodeError:
        raise AuthError("Invalid token: signature, api token is not valid", 403)
    except PyJWTError as e:
        raise AuthError(f"Invalid token: {str(e)}", 403)
    return client


def handle_admin_key(auth_token, secret):
    try:
        decode_jwt_token(auth_token, secret)
    except TokenExpiredError:
        raise AuthError("Invalid token: expired, check that your system clock is accurate", 403)
    except TokenDecodeError:
        raise AuthError("Invalid token: signature, api token is not valid", 403)
