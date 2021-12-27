import json

from typing import Tuple

from authlib.integrations.base_client import OAuthError
from flask import Blueprint, url_for, make_response, redirect, jsonify, current_app, request
from flask_cors.core import get_cors_options, set_cors_headers
from flask_jwt_extended import create_access_token, verify_jwt_in_request
from requests import Response
from requests.exceptions import HTTPError
from sqlalchemy.orm.exc import NoResultFound

from app import statsd_client
from app.dao.users_dao import create_or_retrieve_user, get_user_by_email
from app.errors import register_errors
from app.feature_flags import is_feature_enabled, FeatureFlag
from .exceptions import OAuthException, IncorrectGithubIdException, LoginWithPasswordException, \
    InsufficientGithubScopesException
from app.oauth.registry import oauth_registry
from app.schema_validation import validate
from .auth_schema import password_login_request

oauth_blueprint = Blueprint('oauth', __name__, url_prefix='/auth')
register_errors(oauth_blueprint)


def _assert_github_login_toggle_enabled():
    if not is_feature_enabled(FeatureFlag.GITHUB_LOGIN_ENABLED):
        raise LoginWithPasswordException(message='Not Implemented', status_code=501)


@oauth_blueprint.route('/login', methods=['GET'])
def login():
    _assert_github_login_toggle_enabled()
    redirect_uri = url_for('oauth.authorize', _external=True)
    return oauth_registry.github.authorize_redirect(redirect_uri)


@oauth_blueprint.route('/login', methods=['POST'])
def login_with_password():
    if not is_feature_enabled(FeatureFlag.EMAIL_PASSWORD_LOGIN_ENABLED):
        return jsonify(result='error', message="Not Implemented"), 501

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
    _assert_github_login_toggle_enabled()
    try:
        github_token = oauth_registry.github.authorize_access_token()
        make_github_get_request('/user/memberships/orgs/department-of-veterans-affairs', github_token)
        email_resp = make_github_get_request('/user/emails', github_token)
        user_resp = make_github_get_request('/user', github_token)

        verified_email, verified_user_id, verified_name = _extract_github_user_info(email_resp, user_resp)

        user = create_or_retrieve_user(
            email_address=verified_email,
            identity_provider_user_id=verified_user_id,
            name=verified_name)
    except OAuthError as e:
        current_app.logger.error(f'User denied authorization: {e}')
        statsd_client.incr('oauth.authorization.denied')
        return make_response(redirect(f"{current_app.config['UI_HOST_NAME']}/login/failure?denied_authorization"))
    except (OAuthException, HTTPError) as e:
        current_app.logger.error(f"Authorization exception raised:\n{e}\n")
        statsd_client.incr('oauth.authorization.failure')
        return make_response(redirect(f"{current_app.config['UI_HOST_NAME']}/login/failure"))
    except IncorrectGithubIdException as e:
        current_app.logger.error(e)
        statsd_client.incr('oauth.authorization.github_id_mismatch')
        return make_response(redirect(f"{current_app.config['UI_HOST_NAME']}/login/failure"))
    except InsufficientGithubScopesException as e:
        current_app.logger.error(e)
        statsd_client.incr('oauth.authorization.github_incorrect_scopes')
        return make_response(redirect(f'{current_app.config["UI_HOST_NAME"]}/login/failure?incorrect_scopes'))
    else:
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


def does_user_have_sufficient_scope(response: Response) -> bool:
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
def redeem_token():
    _assert_github_login_toggle_enabled()

    verify_jwt_in_request(locations='cookies')

    cookie = request.cookies.get(current_app.config['JWT_ACCESS_COOKIE_NAME'])
    response = make_response(jsonify({'data': cookie}))

    cors_options = {'origins': current_app.config['UI_HOST_NAME'], 'supports_credentials': True}
    set_cors_headers(response, get_cors_options(current_app, cors_options))

    return response


@oauth_blueprint.route('/logout', methods=['GET'])
def logout():
    _assert_github_login_toggle_enabled()

    response = make_response(redirect(f"{current_app.config['UI_HOST_NAME']}"))
    response.delete_cookie(current_app.config['JWT_ACCESS_COOKIE_NAME'])
    statsd_client.incr('oauth.logout.success')
    return response
