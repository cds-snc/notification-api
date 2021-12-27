import functools
from typing import Callable

from flask import request, current_app, g
from flask_jwt_extended import verify_jwt_in_request, current_user
from flask_jwt_extended.config import config
from notifications_python_client.authentication import decode_jwt_token, get_token_issuer
from notifications_python_client.errors import TokenDecodeError, TokenExpiredError, TokenIssuerError
from notifications_utils import request_helper
from sqlalchemy.exc import DataError
from sqlalchemy.orm.exc import NoResultFound


from app.dao.services_dao import dao_fetch_service_by_id_with_api_keys


class AuthError(Exception):
    def __init__(self, message, code, service_id=None, api_key_id=None):
        self.message = message
        self.short_message = message
        self.code = code
        self.service_id = service_id
        self.api_key_id = api_key_id

    def __str__(self):
        return 'AuthError({message}, {code}, service_id={service_id}, api_key_id={api_key_id})'.format(**self.__dict__)

    def to_dict_v2(self):
        return {
            'status_code': self.code,
            "errors": [
                {
                    "error": "AuthError",
                    "message": self.short_message
                }
            ]
        }


def get_auth_token(req):
    auth_header = req.headers.get('Authorization', None)
    if not auth_header:
        raise AuthError('Unauthorized, authentication token must be provided', 401)

    auth_scheme = auth_header[:7].title()

    if auth_scheme != 'Bearer ':
        raise AuthError('Unauthorized, authentication bearer scheme must be used', 401)

    return auth_header[7:]


def do_not_validate_auth():
    pass


def validate_admin_auth():
    request_helper.check_proxy_header_before_request()

    auth_token = get_auth_token(request)
    client = __get_token_issuer(auth_token)

    if client == current_app.config.get('ADMIN_CLIENT_USER_NAME'):
        g.service_id = current_app.config.get('ADMIN_CLIENT_USER_NAME')
        return handle_admin_key(auth_token, current_app.config.get('ADMIN_CLIENT_SECRET'))
    else:
        raise AuthError('Unauthorized, admin authentication token required', 401)


def create_validator_for_user_in_service_or_admin(required_permission: str = None) -> Callable:

    def _validate_user_in_service_or_platform_admin():

        # when fetching data, the browser may send a pre-flight OPTIONS request.
        # the W3 spec for CORS pre-flight requests states that user credentials should be excluded.
        # hence, for OPTIONS requests, we should skip authentication
        # see https://stackoverflow.com/a/15734032
        if request.method in config.exempt_methods:
            return

        service_id = request.view_args.get('service_id')
        verify_jwt_in_request()

        if (not any(service.id == service_id for service in current_user.services) and not current_user.platform_admin):
            raise AuthError('User is not a member of the specified service', 403, service_id=service_id)

        if required_permission and not current_user.platform_admin:
            user_permissions = current_user.get_permissions(service_id)
            if required_permission not in user_permissions:
                raise AuthError(f'User does not have permission {required_permission}', 403, service_id=service_id)

    return _validate_user_in_service_or_platform_admin


def create_validator_for_admin_auth_or_user_in_service(required_permission: str = None) -> Callable:

    def _validate_admin_auth_or_user_in_service():
        try:
            validate = create_validator_for_user_in_service_or_admin(required_permission)
            validate()
        except AuthError:
            validate_admin_auth()

    return _validate_admin_auth_or_user_in_service


def requires_user_in_service_or_admin(required_permission: str = None):
    def decorator(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            validate = create_validator_for_user_in_service_or_admin(required_permission)
            validate()

            return function(*args, **kwargs)
        return wrapper
    return decorator


def requires_admin_auth_or_user_in_service(required_permission: str = None):
    def decorator(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            validate = create_validator_for_admin_auth_or_user_in_service(required_permission)
            validate()

            return function(*args, **kwargs)
        return wrapper
    return decorator


def requires_admin_auth():
    def decorator(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            validate_admin_auth()
            return function(*args, **kwargs)
        return wrapper
    return decorator


def validate_service_api_key_auth():
    request_helper.check_proxy_header_before_request()

    auth_token = get_auth_token(request)
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
            err_msg = (
                "Error: Your system clock must be accurate to within 30 seconds"
            )
            raise AuthError(err_msg, 403, service_id=service.id, api_key_id=api_key.id)

        if api_key.expiry_date:
            raise AuthError("Invalid token: API key revoked", 403, service_id=service.id, api_key_id=api_key.id)

        g.service_id = api_key.service_id
        g.api_user = api_key
        g.authenticated_service = service
        current_app.logger.info('API authorised for service {} with api key {}, using client {}'.format(
            service.id,
            api_key.id,
            request.headers.get('User-Agent')
        ))
        return
    else:
        # service has API keys, but none matching the one the user provided
        raise AuthError("Invalid token: signature, api token not found", 403, service_id=service.id)


def __get_token_issuer(auth_token):
    try:
        client = get_token_issuer(auth_token)
    except TokenIssuerError:
        raise AuthError("Invalid token: iss field not provided", 403)
    except TokenDecodeError:
        raise AuthError("Invalid token: signature, api token is not valid", 403)
    return client


def handle_admin_key(auth_token, secret):
    try:
        decode_jwt_token(auth_token, secret)
    except TokenExpiredError:
        raise AuthError("Invalid token: expired, check that your system clock is accurate", 403)
    except TokenDecodeError:
        raise AuthError("Invalid token: signature, api token is not valid", 403)
