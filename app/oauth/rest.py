import json
from typing import Tuple

from flask import Blueprint, url_for, make_response, redirect, jsonify, current_app, request
from flask_cors.core import get_cors_options, set_cors_headers
from flask_jwt_extended import create_access_token, verify_jwt_in_request
from flask_jwt_extended.exceptions import NoAuthorizationError
from jwt import ExpiredSignatureError
from requests.exceptions import HTTPError

from app.dao.users_dao import create_or_update_user
from app.errors import register_errors
from app.feature_flags import is_feature_enabled, FeatureFlag
from app.oauth.exceptions import OAuthException
from app.oauth.registry import oauth_registry

oauth_blueprint = Blueprint('oauth', __name__, url_prefix='')
register_errors(oauth_blueprint)


def _assert_toggle_enabled():
    if not is_feature_enabled(FeatureFlag.GITHUB_LOGIN_ENABLED):
        return jsonify(result='error', message="Not Implemented"), 501


oauth_blueprint.before_request(_assert_toggle_enabled)


@oauth_blueprint.route('/login', methods=['GET'])
def login():
    redirect_uri = url_for('oauth.authorize', _external=True)
    return oauth_registry.github.authorize_redirect(redirect_uri)


@oauth_blueprint.route('/authorize')
def authorize():
    github_token = oauth_registry.github.authorize_access_token()

    try:
        make_github_get_request('/user/memberships/orgs/department-of-veterans-affairs', github_token)
        email_resp = make_github_get_request('/user/emails', github_token)
        user_resp = make_github_get_request('/user', github_token)

        verified_email, verified_user_id, verified_name = _extract_github_user_info(email_resp, user_resp)

        user = create_or_update_user(
            email_address=verified_email,
            identity_provider_user_id=verified_user_id,
            name=verified_name)

    except (OAuthException, HTTPError) as e:
        current_app.logger.error(f"Authorization exception raised:\n{e}\n")
        return make_response(redirect(f"{current_app.config['UI_HOST_NAME']}/login/failure"))
    else:
        response = make_response(redirect(current_app.config['UI_HOST_NAME']))
        response.set_cookie(
            current_app.config['JWT_ACCESS_COOKIE_NAME'],
            create_access_token(
                identity=user
            ),
            httponly=True,
            secure=current_app.config['SESSION_COOKIE_SECURE'],
            samesite=current_app.config['SESSION_COOKIE_SAMESITE']
        )
        return response


def make_github_get_request(endpoint: str, github_token) -> json:
    resp = oauth_registry.github.get(
        endpoint,
        token=github_token
    )
    resp.raise_for_status()

    if resp.status_code == 304:
        raise OAuthException(Exception("Fail to retrieve required information to complete authorization"))

    return resp


def _extract_github_user_info(email_resp: json, user_resp: json) -> Tuple[str, str, str]:
    verified_email = next(email.get('email') for email in email_resp.json()
                          if email.get('primary') and email.get('verified'))

    verified_name = user_resp.json().get('name')
    verified_user_id = user_resp.json().get('id')

    return verified_email, verified_user_id, verified_name


@oauth_blueprint.route('/redeem-token', methods=['GET'])
def redeem_token():
    try:
        verify_jwt_in_request(locations='cookies')
    except (NoAuthorizationError, ExpiredSignatureError):
        response = make_response('', 401)
    else:
        cookie = request.cookies.get(current_app.config['JWT_ACCESS_COOKIE_NAME'])
        response = make_response(jsonify({'data': cookie}))

    cors_options = {'origins': current_app.config['UI_HOST_NAME'], 'supports_credentials': True}
    set_cors_headers(response, get_cors_options(current_app, cors_options))

    return response
