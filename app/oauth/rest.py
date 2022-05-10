import json

from typing import Tuple

from authlib.integrations.base_client import OAuthError
from flask import Blueprint, url_for, make_response, redirect, jsonify, current_app, request, Response
from flask_cors.core import get_cors_options, set_cors_headers
from flask_jwt_extended import create_access_token, verify_jwt_in_request
from requests import Response as RequestsResponse
from requests.exceptions import HTTPError
from sqlalchemy.orm.exc import NoResultFound

from app import statsd_client
from app.dao.permissions_dao import permission_dao
from app.model import User
from app.dao.users_dao import create_or_retrieve_user, get_user_by_email, retrieve_match_or_create_user
from app.errors import register_errors
from app.feature_flags import is_feature_enabled, FeatureFlag
from .exceptions import IdpAssignmentException, OAuthException, IncorrectGithubIdException, \
    InsufficientGithubScopesException
from app.oauth.registry import oauth_registry
from app.schema_validation import validate
from .auth_schema import password_login_request
from app.dao.services_dao import dao_fetch_all_services_by_user
from app.schemas import service_schema

oauth_blueprint = Blueprint('oauth', __name__, url_prefix='/auth')
register_errors(oauth_blueprint)


def _assert_toggle_enabled(feature: FeatureFlag):
    if not is_feature_enabled(feature):
        raise NotImplementedError


@oauth_blueprint.route('/login', methods=['GET'])
def login():
    idp = request.args.get('idp')
    if (idp == 'va'):
        _assert_toggle_enabled(FeatureFlag.VA_SSO_ENABLED)
        redirect_uri = url_for('oauth.callback', _external=True)
        return oauth_registry.va_sso.authorize_redirect(redirect_uri)
    else:
        _assert_toggle_enabled(FeatureFlag.GITHUB_LOGIN_ENABLED)
        redirect_uri = url_for('oauth.authorize', _external=True)
        return oauth_registry.github.authorize_redirect(redirect_uri)


@oauth_blueprint.route('/login', methods=['POST'])
def login_with_password():
    _assert_toggle_enabled(FeatureFlag.EMAIL_PASSWORD_LOGIN_ENABLED)

    request_json = request.get_json()
    validate(request_json, password_login_request)

    try:
        fetched_user = get_user_by_email(request_json['email_address'])
    except NoResultFound:
        current_app.logger.info(f"No user was found with email address: {request_json['email_address']}")
    else:
        if fetched_user.check_password(request_json['password']):
            jwt_token = create_access_token(
                identity=fetched_user
            )
            return jsonify(result='success', token=jwt_token), 200
        else:
            current_app.logger.info(f"wrong password for: {request_json['email_address']}")

    return jsonify(result='error', message='Failed to login'), 401


@oauth_blueprint.route('/authorize')
def authorize():
    _assert_toggle_enabled(FeatureFlag.GITHUB_LOGIN_ENABLED)
    try:
        github_token = oauth_registry.github.authorize_access_token()
        make_github_get_request('/user/memberships/orgs/department-of-veterans-affairs', github_token)
        email_resp = make_github_get_request('/user/emails', github_token)
        user_resp = make_github_get_request('/user', github_token)
        verified_email, verified_user_id, verified_name = _extract_github_user_info(email_resp, user_resp)
    except OAuthError as e:
        current_app.logger.error(f'User denied authorization: {e}')
        statsd_client.incr('oauth.authorization.denied')
        return make_response(redirect(f"{current_app.config['UI_HOST_NAME']}/login/failure?denied_authorization"))
    except (OAuthException, HTTPError) as e:
        current_app.logger.error(f"Authorization exception raised:\n{e}\n")
        statsd_client.incr('oauth.authorization.failure')
        return make_response(redirect(f"{current_app.config['UI_HOST_NAME']}/login/failure"))
    except InsufficientGithubScopesException as e:
        current_app.logger.error(e)
        statsd_client.incr('oauth.authorization.github_incorrect_scopes')
        return make_response(redirect(f'{current_app.config["UI_HOST_NAME"]}/login/failure?incorrect_scopes'))
    else:
        if is_feature_enabled(FeatureFlag.VA_SSO_ENABLED):
            return _process_sso_user(
                email=verified_email,
                name=verified_name,
                identity_provider='github',
                identity_provider_user_id=verified_user_id
            )
        else:
            # TODO: Remove below code once VA_SSO_ENABLED toggles is removed
            try:
                user = create_or_retrieve_user(
                    email_address=verified_email,
                    identity_provider_user_id=verified_user_id,
                    name=verified_name)
                return _successful_sso_login_response(user)
            except IncorrectGithubIdException as e:
                current_app.logger.error(e)
                statsd_client.incr('oauth.authorization.github_id_mismatch')
                return make_response(redirect(f"{current_app.config['UI_HOST_NAME']}/login/failure"))


@oauth_blueprint.route('/my-services/<uuid:user_id>', methods=['GET'])
def get_services_by_user(user_id):
    only_active = request.args.get('only_active') == 'True'

    services = dao_fetch_all_services_by_user(user_id, only_active)
    permissions = permission_dao.get_permissions_by_user_id(user_id)

    permissions_by_service = {}
    for user_permission in permissions:
        service_id = str(user_permission.service_id)
        if service_id not in permissions_by_service:
            permissions_by_service[service_id] = []
        permissions_by_service[service_id].append(user_permission.permission)
    data = {
        "services": service_schema.dump(services, many=True).data,
        "permissions": permissions_by_service
    }
    return jsonify(data=data)


@oauth_blueprint.route('/callback')
def callback():
    try:
        tokens = oauth_registry.va_sso.authorize_access_token()
        user_info = oauth_registry.va_sso.parse_id_token(tokens)
        return _process_sso_user(
            email=user_info['email'],
            name=f"{user_info['given_name']} {user_info['family_name']}",
            identity_provider='va_sso',
            identity_provider_user_id=user_info['sub']
        )
    except OAuthError as e:
        current_app.logger.exception(e)
        statsd_client.incr('oauth.authorization.denied')
        response = make_response({'error': e.error, 'description': e.description}, 401)
        return response
    except Exception as e:
        current_app.logger.exception(e)
        statsd_client.incr('oauth.authorization.failure')
        response = make_response({'error': 'Unauthorized', 'description': 'Authentication failure'}, 401)
        return response


def _process_sso_user(email: str, name: str, identity_provider: str, identity_provider_user_id: str) -> Response:
    try:
        user = retrieve_match_or_create_user(
            email_address=email,
            name=name,
            identity_provider=identity_provider,
            identity_provider_user_id=identity_provider_user_id
        )
    except IdpAssignmentException as e:
        current_app.logger.exception(e)
        statsd_client.incr('oauth.authorization.idpassignmentexception')
        response = make_response({'error': 'Unauthorized', 'description': 'IDP authentication failure'}, 401)
        return response
    except Exception as e:
        current_app.logger.exception(e)
        statsd_client.incr('oauth.authorization.failure')
        response = make_response({'error': 'Unauthorized', 'description': 'Authentication failure'}, 401)
        return response
    else:
        return _successful_sso_login_response(user)


def _successful_sso_login_response(user: User) -> Response:
    response = make_response(redirect(f"{current_app.config['UI_HOST_NAME']}/login/success"))
    response.set_cookie(
        current_app.config['JWT_ACCESS_COOKIE_NAME'],
        create_access_token(
            identity=user
        ),
        httponly=True,
        secure=current_app.config['SESSION_COOKIE_SECURE'],
        samesite=current_app.config['SESSION_COOKIE_SAMESITE']
    )
    statsd_client.incr('oauth.authorization.success')
    current_app.logger.info(f"Successful SSO authorization for {user.id}")
    return response


def make_github_get_request(endpoint: str, github_token) -> json:
    resp = oauth_registry.github.get(
        endpoint,
        token=github_token
    )

    if not does_user_have_sufficient_scope(resp):
        raise InsufficientGithubScopesException

    if resp.status_code in [403, 404]:
        exception = OAuthException
        exception.status_code = 401
        exception.message = "User Account not found."
        raise exception

    if resp.status_code == 304:
        raise OAuthException(Exception("Fail to retrieve required information to complete authorization"))

    resp.raise_for_status()

    return resp


def does_user_have_sufficient_scope(response: RequestsResponse) -> bool:
    if is_feature_enabled(FeatureFlag.CHECK_GITHUB_SCOPE_ENABLED):
        oauth_scopes_from_token = response.headers['X-OAuth-Scopes'].split(', ')
        required_scopes = {'read:user', 'user:email', 'read:org'}

        return required_scopes.issubset(set(oauth_scopes_from_token))
    else:
        return True


def _extract_github_user_info(email_resp: json, user_resp: json) -> Tuple[str, str, str]:
    verified_email = next(email.get('email') for email in email_resp.json()
                          if email.get('primary') and email.get('verified'))

    verified_name = user_resp.json().get('name') or user_resp.json().get('login')
    verified_user_id = user_resp.json().get('id')

    return verified_email, verified_user_id, verified_name


@oauth_blueprint.route('/redeem-token', methods=['GET'])
@oauth_blueprint.route('/token', methods=['GET'])
def token():
    verify_jwt_in_request(locations='cookies')

    cookie = request.cookies.get(current_app.config['JWT_ACCESS_COOKIE_NAME'])
    response = make_response(jsonify({'data': cookie}))

    cors_options = {'origins': current_app.config['UI_HOST_NAME'], 'supports_credentials': True}
    set_cors_headers(response, get_cors_options(current_app, cors_options))

    return response


@oauth_blueprint.route('/logout', methods=['GET'])
def logout():
    response = make_response(redirect(f"{current_app.config['UI_HOST_NAME']}"))
    response.delete_cookie(current_app.config['JWT_ACCESS_COOKIE_NAME'])
    statsd_client.incr('oauth.logout.success')
    return response
