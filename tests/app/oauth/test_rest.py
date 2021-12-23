import json
import os
from typing import Dict

import pytest
from authlib.integrations.base_client import OAuthError
from flask_jwt_extended.exceptions import NoAuthorizationError
from requests import Response
from requests.exceptions import HTTPError
from sqlalchemy.orm.exc import NoResultFound

from app.feature_flags import FeatureFlag
from app.models import User
from app.oauth.exceptions import OAuthException, IncorrectGithubIdException, InsufficientGithubScopesException
from app.oauth.rest import make_github_get_request
from tests.conftest import set_config_values


def mock_toggle(mocker, feature_flag: FeatureFlag, enabled: str) -> None:
    mocker.patch.dict(os.environ, {feature_flag.value: enabled})


cookie_config = {
    'UI_HOST_NAME': 'https://some-ui-host-name.com',
    'JWT_ACCESS_COOKIE_NAME': 'cookie-name'
}


@pytest.fixture(autouse=True)
def github_login_toggle_enabled(mocker):
    mock_toggle(mocker, FeatureFlag.GITHUB_LOGIN_ENABLED, 'True')


github_org_membership = {
    "url": "https://api.github.com/orgs/department-of-veterans-affairs/memberships/some-user",
    "state": "pending",
    "role": "user",
    "organization_url": "https://api.github.com/orgs/department-of-veterans-affairs",
    "organization": {
        "login": "department-of-veterans-affairs",
        "id": 1,
        "node_id": "blahblahblah",
        "url": "https://api.github.com/orgs/department-of-veterans-affairs",
        "repos_url": "https://api.github.com/orgs/department-of-veterans-affairs/repos",
        "events_url": "https://api.github.com/orgs/department-of-veterans-affairs/events",
        "hooks_url": "https://api.github.com/orgs/department-of-veterans-affairs/hooks",
        "issues_url": "https://api.github.com/orgs/department-of-veterans-affairs/issues",
        "members_url": "https://api.github.com/orgs/department-of-veterans-affairs/members/someuser",
        "public_members_url": "https://api.github.com/orgs/department-of-veterans-affairs/public_members/someuser",
        "avatar_url": "https://github.com/images/error/octocat_happy.gif",
        "description": "Some organization"
    },
    "user": {
        "login": "someuser",
        "id": 1,
        "node_id": "MDQ6VXNlcjE=",
        "avatar_url": "https://github.com/images/error/octocat_happy.gif",
        "gravatar_id": "",
        "url": "https://api.github.com/users/someuser",
        "html_url": "https://github.com/someuser",
        "followers_url": "https://api.github.com/users/someuser/followers",
        "following_url": "https://api.github.com/users/someuser/following{/other_user}",
        "gists_url": "https://api.github.com/users/someuser/gists{/gist_id}",
        "starred_url": "https://api.github.com/users/someuser/starred{/owner}{/repo}",
        "subscriptions_url": "https://api.github.com/users/someuser/subscriptions",
        "organizations_url": "https://api.github.com/users/someuser/orgs",
        "repos_url": "https://api.github.com/users/someuser/repos",
        "events_url": "https://api.github.com/users/someuser/events{/privacy}",
        "received_events_url": "https://api.github.com/users/someuser/received_events",
        "type": "User",
        "site_admin": False
    }
}


github_user = {
    "login": "someuser",
    "id": 1,
    "node_id": "MDQ6VXNlcjE=",
    "avatar_url": "https://github.com/images/error/octocat_happy.gif",
    "gravatar_id": "",
    "url": "https://api.github.com/users/someuser",
    "html_url": "https://github.com/someuser",
    "followers_url": "https://api.github.com/users/someuser/followers",
    "following_url": "https://api.github.com/users/someuser/following{/other_user}",
    "gists_url": "https://api.github.com/users/someuser/gists{/gist_id}",
    "starred_url": "https://api.github.com/users/someuser/starred{/owner}{/repo}",
    "subscriptions_url": "https://api.github.com/someuser/octocat/subscriptions",
    "organizations_url": "https://api.github.com/someuser/octocat/orgs",
    "repos_url": "https://api.github.com/users/someuser/repos",
    "events_url": "https://api.github.com/users/someuser/events{/privacy}",
    "received_events_url": "https://api.github.com/users/someuser/received_events",
    "type": "User",
    "site_admin": False,
    "name": "monalisa someuser",
    "company": "GitHub",
    "blog": "https://github.com/blog",
    "location": "San Francisco",
    "email": "octocat@github.com",
    "hireable": False,
    "bio": "There once was...",
    "twitter_username": "monatheoctocat",
    "public_repos": 2,
    "public_gists": 1,
    "followers": 20,
    "following": 0,
    "created_at": "2008-01-14T04:33:35Z",
    "updated_at": "2008-01-14T04:33:35Z",
    "private_gists": 81,
    "total_private_repos": 100,
    "owned_private_repos": 100,
    "disk_usage": 10000,
    "collaborators": 8,
    "two_factor_authentication": True,
    "plan": {
        "name": "Medium",
        "space": 400,
        "private_repos": 20,
        "collaborators": 0
    }
}


github_user_emails = [
    {
        "email": "some.user@thoughtworks.com",
        "verified": True,
        "primary": True,
        "visibility": "public"
    }
]


def get_github_response_map(mocker, custom_responses: Dict[str, Dict] = None):
    responses = {
        '/user/memberships/orgs/department-of-veterans-affairs': github_org_membership,
        '/user/emails': github_user_emails,
        '/user': github_user,
    }

    if custom_responses:
        for endpoint, response in custom_responses.items():
            responses[endpoint] = response

    for endpoint, response in responses.items():
        responses[endpoint] = mocker.Mock(Response, json=mocker.Mock(return_value=response))

    return responses


def mock_github_responses(mocker, custom_responses: Dict[str, Dict] = None):
    response_map = get_github_response_map(mocker, custom_responses)
    mocker.patch(
        'app.oauth.rest.make_github_get_request',
        side_effect=lambda endpoint, _token: response_map[endpoint]
    )


@pytest.fixture(autouse=True)
def mock_default_github_user_responses(mocker):
    mock_github_responses(mocker)


@pytest.fixture(autouse=True)
def mock_github_authorize_access_token(mocker):
    return mocker.patch('app.oauth.rest.oauth_registry.github.authorize_access_token')


class TestLogin:

    def test_should_return_501_if_toggle_is_disabled(self, client, mocker):
        mock_toggle(mocker, FeatureFlag.GITHUB_LOGIN_ENABLED, 'False')

        response = client.get('/auth/login')

        assert response.status_code == 501

    def test_should_redirect_to_github_if_toggle_is_enabled(
            self, client
    ):
        response = client.get('/auth/login')

        assert response.status_code == 302
        assert 'https://github.com/login/oauth/authorize' in response.location


class TestAuthorize:

    def test_should_return_501_if_toggle_is_disabled(self, client, mocker):
        mock_toggle(mocker, FeatureFlag.GITHUB_LOGIN_ENABLED, 'False')

        response = client.get('/auth/authorize')

        assert response.status_code == 501

    @pytest.mark.parametrize('exception', [OAuthException, HTTPError])
    def test_should_redirect_to_login_failure_if_organization_membership_verification_or_user_info_retrieval_fails(
            self, client, notify_api, mocker, exception
    ):
        mock_logger = mocker.patch('app.oauth.rest.current_app.logger.error')
        mocker.patch(
            'app.oauth.rest.make_github_get_request',
            side_effect=exception
        )

        with set_config_values(notify_api, cookie_config):
            response = client.get('/auth/authorize')

        assert response.status_code == 302
        assert f"{cookie_config['UI_HOST_NAME']}/login/failure" in response.location
        assert not any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME'] for cookie in client.cookie_jar
        )
        mock_logger.assert_called_once()

    def test_should_redirect_to_login_failure_if_incorrect_github_id(
            self, client, notify_api, mocker
    ):
        mocker.patch('app.oauth.rest.create_access_token', return_value='some-access-token-value')
        mocker.patch('app.oauth.rest.create_or_retrieve_user', side_effect=IncorrectGithubIdException)
        mock_logger = mocker.patch('app.oauth.rest.current_app.logger.error')

        with set_config_values(notify_api, cookie_config):
            response = client.get('/auth/authorize')

        assert response.status_code == 302
        assert f"{cookie_config['UI_HOST_NAME']}/login/failure" in response.location
        assert not any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME'] for cookie in client.cookie_jar
        )
        mock_logger.assert_called_once()

    def test_should_redirect_to_login_denied_if_user_denies_access(
            self, client, notify_api, mocker, mock_github_authorize_access_token
    ):
        mock_github_authorize_access_token.side_effect = OAuthError
        mock_logger = mocker.patch('app.oauth.rest.current_app.logger.error')

        with set_config_values(notify_api, cookie_config):
            response = client.get('/auth/authorize')

        assert response.status_code == 302
        assert f"{cookie_config['UI_HOST_NAME']}/login/failure?denied_authorization" in response.location
        assert not any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME'] for cookie in client.cookie_jar
        )
        mock_logger.assert_called_once()

    def test_should_raise_exception_if_304_from_github_get(
            self, client, notify_api, mocker
    ):
        mock_toggle(mocker, FeatureFlag.CHECK_GITHUB_SCOPE_ENABLED, 'True')
        github_get_user_resp = mocker.Mock(
            Response, status_code=304, headers={'X-OAuth-Scopes': 'read:user, user:email, read:org'}
        )

        mocker.patch(
            'app.oauth.rest.oauth_registry.github.get',
            return_value=github_get_user_resp,
        )

        with pytest.raises(OAuthException):
            make_github_get_request('/user', 'fake-token')

    @pytest.mark.parametrize('status_code', [403, 404])
    def test_should_raise_http_error_if_error_from_github_get(
            self, client, notify_api, mocker, status_code
    ):
        mock_toggle(mocker, FeatureFlag.CHECK_GITHUB_SCOPE_ENABLED, 'True')
        github_get_user_resp = mocker.Mock(
            Response, status_code=status_code, headers={'X-OAuth-Scopes': 'read:user, user:email, read:org'}
        )

        mocker.patch(
            'app.oauth.rest.oauth_registry.github.get',
            return_value=github_get_user_resp,
        )

        with pytest.raises(OAuthException) as e:
            make_github_get_request('/user', 'fake-token')

        assert e.value.status_code == 401
        assert e.value.message == 'User Account not found.'

    def test_should_raise_insufficient_github_scopes_exception_if_missing_scopes(
            self, client, notify_api, mocker
    ):
        mock_toggle(mocker, FeatureFlag.CHECK_GITHUB_SCOPE_ENABLED, 'True')
        github_get_user_resp = mocker.Mock(
            Response, status_code=200, headers={'X-OAuth-Scopes': 'read:org'}
        )

        mocker.patch(
            'app.oauth.rest.oauth_registry.github.get',
            return_value=github_get_user_resp,
        )

        with pytest.raises(InsufficientGithubScopesException):
            make_github_get_request('/user', 'fake-token')

    def test_should_not_raise_insufficient_github_scopes_exception_if_not_missing_scopes(
            self, client, notify_api, mocker
    ):
        mock_toggle(mocker, FeatureFlag.CHECK_GITHUB_SCOPE_ENABLED, 'True')
        github_get_user_resp = mocker.Mock(
            Response, status_code=200, headers={'X-OAuth-Scopes': 'read:user, user:email, read:org'}
        )

        mocker.patch(
            'app.oauth.rest.oauth_registry.github.get',
            return_value=github_get_user_resp,
        )

        resp = make_github_get_request('/user', 'fake-token')
        assert resp.status_code == 200

    def test_should_redirect_to_ui_if_user_is_member_of_va_organization(
            self, client, notify_api, mocker
    ):
        found_user = User()
        mocker.patch('app.oauth.rest.create_or_retrieve_user', return_value=found_user)
        create_access_token = mocker.patch('app.oauth.rest.create_access_token', return_value='some-access-token-value')

        with set_config_values(notify_api, cookie_config):
            response = client.get('/auth/authorize')

        create_access_token.assert_called_with(identity=found_user)

        assert response.status_code == 302
        assert response.location == f"{cookie_config['UI_HOST_NAME']}/login/success"

        assert any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME']
            and cookie.value == 'some-access-token-value'
            for cookie in client.cookie_jar
        )

    @pytest.mark.parametrize('identity_provider_user_id', [None, '1'])
    def test_should_create_or_update_existing_user_with_identity_provider_user_id_when_successfully_verified(
            self, client, notify_api, mocker, identity_provider_user_id
    ):
        expected_email = github_user_emails[0]['email']
        expected_user_id = github_org_membership['user']['id']
        expected_name = github_user['name']

        found_user = User(
            email_address=expected_email,
            identity_provider_user_id=identity_provider_user_id,
            name=expected_name
        )
        create_or_retrieve_user = mocker.patch(
            'app.oauth.rest.create_or_retrieve_user', return_value=found_user
        )

        mocker.patch('app.oauth.rest.create_access_token', return_value='some-access-token-value')

        with set_config_values(notify_api, cookie_config):
            client.get('/auth/authorize')

        create_or_retrieve_user.assert_called_with(
            email_address=expected_email,
            identity_provider_user_id=expected_user_id,
            name=expected_name)

    def test_should_create_user_with_login_name_if_no_name_in_response(
            self, client, notify_api, mocker
    ):
        github_user_with_no_name = github_user.copy()
        github_user_with_no_name['name'] = None
        github_user_with_no_name['login'] = 'some-user-name-that-is-not-a-real-name'

        mock_github_responses(mocker, {'/user': github_user_with_no_name})

        create_or_retrieve_user = mocker.patch('app.oauth.rest.create_or_retrieve_user')

        mocker.patch('app.oauth.rest.create_access_token', return_value='some-access-token-value')

        with set_config_values(notify_api, cookie_config):
            client.get('/auth/authorize')

        _args, kwargs = create_or_retrieve_user.call_args
        assert kwargs['name'] == 'some-user-name-that-is-not-a-real-name'


class TestRedeemToken:

    def test_should_return_501_if_toggle_is_disabled(self, client, mocker):
        mock_toggle(mocker, FeatureFlag.GITHUB_LOGIN_ENABLED, 'False')

        response = client.get('/auth/redeem-token')

        assert response.status_code == 501

    def test_should_return_401_if_cookie_verification_fails(
            self, client, mocker
    ):
        mocker.patch('app.oauth.rest.verify_jwt_in_request', side_effect=NoAuthorizationError())
        response = client.get('/auth/redeem-token')

        assert response.status_code == 401

    def test_should_return_cookie_in_body(
            self, client, mocker, notify_api
    ):
        mocker.patch('app.oauth.rest.verify_jwt_in_request', side_effect=None)

        expected_cookie_value = 'some-cookie-value'
        client.set_cookie('test',
                          cookie_config['JWT_ACCESS_COOKIE_NAME'],
                          expected_cookie_value)

        with set_config_values(notify_api,
                               {'JWT_ACCESS_COOKIE_NAME': cookie_config['JWT_ACCESS_COOKIE_NAME']}
                               ):
            response = client.get('/auth/redeem-token')

        assert response.status_code == 200
        assert response.json.get('data') == expected_cookie_value

    def test_should_set_cors_headers(self, client, mocker, notify_api):
        mocker.patch('app.oauth.rest.verify_jwt_in_request', side_effect=None)

        with set_config_values(notify_api, {
            'UI_HOST_NAME': cookie_config['UI_HOST_NAME']
        }):
            response = client.get('/auth/redeem-token')

        assert response.access_control_allow_credentials
        assert response.access_control_allow_origin == cookie_config['UI_HOST_NAME']


class TestLoginWithPassword:

    @pytest.fixture(autouse=True)
    def login_with_password_toggle_enabled(self, mocker):
        mock_toggle(mocker, FeatureFlag.EMAIL_PASSWORD_LOGIN_ENABLED, 'True')

    def test_login_with_password_succeeds_when_correct_credentials(self, notify_db_session, client, mocker):
        some_p = 'sillypassword'
        user = User()
        user.password = some_p
        mocker.patch('app.oauth.rest.get_user_by_email', return_value=user)
        data = {
            "email_address": "dummy@email.address",
            "password": some_p
        }

        response = client.post('/auth/login', data=json.dumps(data), headers=[('Content-Type', 'application/json')])
        assert response.status_code == 200

    def test_should_return_501_if_password_toggle_is_disabled(self, mocker, client):
        mock_toggle(mocker, FeatureFlag.EMAIL_PASSWORD_LOGIN_ENABLED, 'False')

        response = client.post('/auth/login')

        assert response.status_code == 501

    def test_should_return_400_when_email_address_or_password_not_present_in_body(self, client):
        response = client.post('/auth/login', data=json.dumps({}), headers=[('Content-Type', 'application/json')])

        assert response.status_code == 400

    def test_should_return_401_when_wrong_password(self, client, mocker):
        user = User()
        user.password = 'correct_password'

        mocker.patch('app.oauth.rest.get_user_by_email', return_value=user)

        response = client.post(
            '/auth/login',
            data=json.dumps({
                "email_address": "some@email.address",
                "password": 'incorrect_password'
            }),
            headers=[('Content-Type', 'application/json')]
        )

        assert response.status_code == 401

    def test_should_return_401_when_user_not_found_by__email_address(self, client, mocker):
        mocker.patch('app.oauth.rest.get_user_by_email', side_effect=NoResultFound)

        response = client.post(
            '/auth/login',
            data=json.dumps({
                "email_address": "some@email.address",
                "password": 'silly-me'
            }),
            headers=[('Content-Type', 'application/json')]
        )
        assert response.status_code == 401

    def test_login_with_password_success_returns_token(self, notify_db_session, client, mocker):
        password = 'sillypassword'
        email_address = 'success@email.address'

        user = User(email_address=email_address)
        user.password = password

        mocker.patch('app.oauth.rest.get_user_by_email', return_value=user)

        response = client.post(
            '/auth/login',
            data=json.dumps({
                "email_address": email_address,
                "password": password
            }),
            headers=[('Content-Type', 'application/json')]
        )

        response_json = response.json
        assert response_json['result'] == 'success'
        assert response_json['token'] is not None


class TestLogout:

    def test_should_return_501_if_toggle_is_disabled(self, client, mocker):
        mock_toggle(mocker, FeatureFlag.GITHUB_LOGIN_ENABLED, 'False')

        response = client.get('/auth/logout')

        assert response.status_code == 501

    def test_should_redirect_to_ui_and_clear_cookies(
            self, client, notify_api, db_session
    ):
        with set_config_values(notify_api, cookie_config):
            client.get('/auth/authorize')

        assert any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME']
            for cookie in client.cookie_jar
        )

        with set_config_values(notify_api, cookie_config):
            response = client.get('/auth/logout')

        assert response.status_code == 302
        assert cookie_config['UI_HOST_NAME'] in response.location

        assert not any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME']
            for cookie in client.cookie_jar
        )
