from flask import Blueprint, url_for, make_response, redirect, jsonify, current_app, request
from flask_cors.core import get_cors_options, set_cors_headers
from flask_jwt_extended import create_access_token, verify_jwt_in_request
from flask_jwt_extended.exceptions import NoAuthorizationError
from jwt import ExpiredSignatureError

from app.dao.users_dao import create_or_update_user
from app.errors import register_errors
from app.feature_flags import is_feature_enabled, FeatureFlag
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

    org_membership_resp = oauth_registry.github.get(
        '/user/memberships/orgs/department-of-veterans-affairs',
        token=github_token
    )
    org_membership_resp.raise_for_status()
    if org_membership_resp.status_code != 200:
        return make_response(redirect(f"{current_app.config['UI_HOST_NAME']}/login/failure"))

    email_resp = oauth_registry.github.get('/user/emails', token=github_token)
    email_resp.raise_for_status()
    verified_thoughtworks_email = next(email.get('email') for email in email_resp.json()
                                       if email.get('primary') and email.get('verified'))

    name_resp = oauth_registry.github.get('/user', token=github_token)
    name_resp.raise_for_status()
    verified_name, verified_github_login = (name_resp.json().get('name'), name_resp.json().get('login'))

    user = create_or_update_user(
        email_address=verified_thoughtworks_email,
        identity_provider_user_id=verified_github_login,
        name=verified_name)

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
