import json
import pytest
from typing import Dict
from authlib.integrations.base_client import OAuthError
from flask_jwt_extended.exceptions import NoAuthorizationError
from flask_jwt_extended import decode_token
from requests import Response
from requests.exceptions import HTTPError
from sqlalchemy.orm.exc import NoResultFound

from app.feature_flags import FeatureFlag
from app.model import User
from app.oauth.exceptions import (IdpAssignmentException, OAuthException,
                                  IncorrectGithubIdException, InsufficientGithubScopesException)
from app.oauth.rest import make_github_get_request
from tests.conftest import set_config_values
from tests.app.factories.feature_flag import mock_feature_flag

cookie_config = {
    'UI_HOST_NAME': 'https://some-ui-host-name.com',
    'JWT_ACCESS_COOKIE_NAME': 'cookie-name',
    'SESSION_COOKIE_SECURE': True
}


@pytest.fixture(scope="module", autouse=True)
def configure_cookie(notify_api):
    with set_config_values(notify_api, cookie_config):
        yield


@pytest.fixture(autouse=True)
def github_login_toggle_enabled(mocker):
    mock_feature_flag(mocker, FeatureFlag.GITHUB_LOGIN_ENABLED, 'True')
    mock_feature_flag(mocker, FeatureFlag.CHECK_GITHUB_SCOPE_ENABLED, 'True')


@pytest.fixture(autouse=True)
def va_sso_toggle_enabled(mocker):
    mock_feature_flag(mocker, FeatureFlag.VA_SSO_ENABLED, 'True')


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


@pytest.fixture(autouse=True)
def mock_statsd(mocker):
    return mocker.patch('app.oauth.rest.statsd_client')


id_token = "id_token"
tokens = {'token_type': 'Bearer', 'expires_in': 3600, 'scope': 'openid profile email',
          'id_token': id_token, 'expires_at': 1568044390}
va_sso_user_info = {
    "fediamMVIICN": "1010031911V591044",
    "nonce": "123",
    "email": "FIRST.LASTNAME@VA.GOV",
    "iat": 1568040790,
    "iss": "https://sqa.fed.eauth.va.gov/oauthi/sps/oauth/oauth20/metadata/ISAMOP",
    "at_hash": "bFo9KMdkW5ov7eBAWjfHhg",
    "sub": "1010031911",
    "fediamVAUID": "22128",
    "family_name": "LASTNAME",
    "fediamadSamAccountName": "VHAISWSMITRE",
    "given_name": "FIRST",
    "fediamsecid": "1010031911",
    "exp": 1568044390,
    "aud": "ampl_gui"
}


@pytest.fixture(autouse=True)
def mock_va_sso_authorize_access_token(mocker):
    return mocker.patch('app.oauth.rest.oauth_registry.va_sso.authorize_access_token', return_value=tokens)


@pytest.fixture(autouse=True)
def mock_va_sso_parse_id_token(mocker):
    return mocker.patch('app.oauth.rest.oauth_registry.va_sso.parse_id_token', return_value=va_sso_user_info)


class TestLogin:

    def test_should_return_501_if_toggle_is_disabled(self, client, mocker):
        mock_feature_flag(mocker, FeatureFlag.GITHUB_LOGIN_ENABLED, 'False')

        response = client.get('/auth/login')

        assert response.status_code == 501

    def test_should_redirect_to_github_if_toggle_is_enabled(
            self, client
    ):
        response = client.get('/auth/login')

        assert response.status_code == 302
        assert 'https://github.com/login/oauth/authorize' in response.location

    @pytest.mark.parametrize('feature, idp', [
        (FeatureFlag.GITHUB_LOGIN_ENABLED, 'github'),
        (FeatureFlag.VA_SSO_ENABLED, 'va')
    ])
    def test_should_return_501_for_given_idp(self, client, mocker, feature, idp):
        mock_feature_flag(mocker, feature, 'False')
        response = client.get(f'/auth/login?idp={idp}')
        assert response.status_code == 501

    @pytest.mark.parametrize('idp, url', [
        ('github', 'https://github.com/login/oauth/authorize'),
        ('va', 'https://int.fed.eauth.va.gov/oauthi/sps/oauth/oauth20/authorize')
    ])
    def test_should_redirect_to_idp_if_toggle_is_enabled(self, client, va_sso_toggle_enabled, idp, url):
        response = client.get(f'/auth/login?idp={idp}')

        assert response.status_code == 302
        assert url in response.location


class TestMakeGithubGetRequest:
    def test_should_raise_exception_if_304_from_github_get(
            self, client, notify_api, mocker
    ):
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
        github_get_user_resp = mocker.Mock(
            Response, status_code=200, headers={'X-OAuth-Scopes': 'read:user, user:email, read:org'}
        )

        mocker.patch(
            'app.oauth.rest.oauth_registry.github.get',
            return_value=github_get_user_resp,
        )

        resp = make_github_get_request('/user', 'fake-token')
        assert resp.status_code == 200


class TestSsoCommon:
    @pytest.mark.parametrize('path', [
        'authorize',
        'callback'
    ])
    def test_returns_401_on_idp_assignment_exception(self, client, mocker, mock_statsd, path):
        mocker.patch('app.oauth.rest.retrieve_match_or_create_user').side_effect = IdpAssignmentException()
        response = client.get(f'/auth/{path}')

        assert response.status_code == 401
        assert response.json == {"error": "Unauthorized", "description": "IDP authentication failure"}
        assert mock_statsd.incr.called_with('oauth.authorization.idpassignmentexception')

    @pytest.mark.parametrize('path', [
        'authorize',
        'callback'
    ])
    def test_returns_401_on_any_exception(self, client, mocker, mock_statsd, path):
        mocker.patch('app.oauth.rest.retrieve_match_or_create_user').side_effect = Exception()
        response = client.get(f'/auth/{path}')

        assert response.status_code == 401
        assert response.json == {"error": "Unauthorized", "description": "Authentication failure"}
        assert mock_statsd.incr.called_with('oauth.authorization.failure')

    @pytest.mark.parametrize('path', [
        'authorize',
        'callback'
    ])
    def test_redirects_to_ui_and_sets_token_in_cookie(self, client, sample_user, mock_statsd, mocker, path):
        mocker.patch('app.oauth.rest.retrieve_match_or_create_user', return_value=sample_user)
        response = client.get(f'/auth/{path}')

        assert response.status_code == 302
        assert response.location == f"{cookie_config['UI_HOST_NAME']}/login/success"

        cookie = list(client.cookie_jar)[0]
        assert cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME']
        assert cookie.secure is True
        user = decode_token(cookie.value)
        assert user['sub']['id'] == str(sample_user.id)
        assert mock_statsd.incr.called_with('oauth.authorization.success')


class TestAuthorize:
    def test_should_return_501_if_toggle_is_disabled(self, client, mocker):
        mock_feature_flag(mocker, FeatureFlag.GITHUB_LOGIN_ENABLED, 'False')
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

        response = client.get('/auth/authorize')

        assert response.status_code == 302
        assert f"{cookie_config['UI_HOST_NAME']}/login/failure?denied_authorization" in response.location
        assert not any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME'] for cookie in client.cookie_jar
        )
        mock_logger.assert_called_once()

    def test_extracts_user_info_and_calls_dao_method(self, client, sample_user, mocker):
        mocked_dao = mocker.patch('app.oauth.rest.retrieve_match_or_create_user', return_value=sample_user)
        client.get('/auth/authorize')

        expected_email = github_user_emails[0]['email']
        expected_user_id = github_org_membership['user']['id']
        expected_name = github_user['name']

        mocked_dao.assert_called_with(
            email_address=expected_email,
            name=expected_name,
            identity_provider='github',
            identity_provider_user_id=expected_user_id)


class TestAuthorizeWhenVaSsoToggleIsOff:
    @pytest.fixture(autouse=True)
    def va_sso_toggle_enabled(self, mocker):
        mock_feature_flag(mocker, FeatureFlag.VA_SSO_ENABLED, 'False')

    def test_should_redirect_to_login_failure_if_incorrect_github_id(
            self, client, mocker
    ):
        mocker.patch('app.oauth.rest.create_access_token', return_value='some-access-token-value')
        mocker.patch('app.oauth.rest.create_or_retrieve_user', side_effect=IncorrectGithubIdException)
        mock_logger = mocker.patch('app.oauth.rest.current_app.logger.error')

        response = client.get('/auth/authorize')

        assert response.status_code == 302
        assert f"{cookie_config['UI_HOST_NAME']}/login/failure" in response.location
        assert not any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME'] for cookie in client.cookie_jar
        )
        mock_logger.assert_called_once()

    def test_should_redirect_to_ui_if_user_is_member_of_va_organization(
            self, client, mocker
    ):
        found_user = User()
        mocker.patch('app.oauth.rest.create_or_retrieve_user', return_value=found_user)
        create_access_token = mocker.patch('app.oauth.rest.create_access_token', return_value='some-access-token-value')

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
            self, client, mocker, identity_provider_user_id
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

        client.get('/auth/authorize')

        create_or_retrieve_user.assert_called_with(
            email_address=expected_email,
            identity_provider_user_id=expected_user_id,
            name=expected_name)

    def test_should_create_user_with_login_name_if_no_name_in_response(
            self, client, mocker
    ):
        github_user_with_no_name = github_user.copy()
        github_user_with_no_name['name'] = None
        github_user_with_no_name['login'] = 'some-user-name-that-is-not-a-real-name'

        mock_github_responses(mocker, {'/user': github_user_with_no_name})

        create_or_retrieve_user = mocker.patch('app.oauth.rest.create_or_retrieve_user')

        mocker.patch('app.oauth.rest.create_access_token', return_value='some-access-token-value')

        client.get('/auth/authorize')

        _args, kwargs = create_or_retrieve_user.call_args
        assert kwargs['name'] == 'some-user-name-that-is-not-a-real-name'


class TestRedeemToken:

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

        response = client.get('/auth/redeem-token')

        assert response.status_code == 200
        assert response.json.get('data') == expected_cookie_value

    def test_should_set_cors_headers(self, client, mocker, notify_api):
        mocker.patch('app.oauth.rest.verify_jwt_in_request', side_effect=None)

        response = client.get('/auth/redeem-token')

        assert response.access_control_allow_credentials
        assert response.access_control_allow_origin == cookie_config['UI_HOST_NAME']


class TestLoginWithPassword:

    @pytest.fixture(autouse=True)
    def login_with_password_toggle_enabled(self, mocker):
        mock_feature_flag(mocker, FeatureFlag.EMAIL_PASSWORD_LOGIN_ENABLED, 'True')

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
        mock_feature_flag(mocker, FeatureFlag.EMAIL_PASSWORD_LOGIN_ENABLED, 'False')

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

    def test_should_redirect_to_ui_and_clear_cookies(self, client, db_session, sample_user, mocker):
        mocker.patch('app.oauth.rest.retrieve_match_or_create_user', return_value=sample_user)
        client.get('/auth/authorize')

        assert any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME']
            for cookie in client.cookie_jar
        )

        response = client.get('/auth/logout')

        assert response.status_code == 302
        assert cookie_config['UI_HOST_NAME'] in response.location

        assert not any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME']
            for cookie in client.cookie_jar
        )


class TestCallback:
    def test_extracts_user_info_and_calls_dao_method(self, client, sample_user, mocker):
        mocked_dao = mocker.patch('app.oauth.rest.retrieve_match_or_create_user', return_value=sample_user)
        client.get('/auth/callback')

        mocked_dao.assert_called_with(
            email_address=va_sso_user_info['email'],
            name=f"{va_sso_user_info['given_name']} {va_sso_user_info['family_name']}",
            identity_provider='va_sso',
            identity_provider_user_id=va_sso_user_info['sub'])

    def test_returns_401_on_oauth_error(self, client, mock_va_sso_authorize_access_token, mock_statsd):
        mock_va_sso_authorize_access_token.side_effect = OAuthError(error="some error", description="some description")
        response = client.get('/auth/callback')

        assert response.status_code == 401
        assert response.json == {"error": "some error", "description": "some description"}
        assert mock_statsd.incr.called_with('oauth.authorization.denied')

    def test_returns_401_on_any_exception(self, client, mock_va_sso_authorize_access_token, mock_statsd):
        mock_va_sso_authorize_access_token.side_effect = Exception()
        response = client.get('/auth/callback')

        assert response.status_code == 401
        assert response.json == {"error": "Unauthorized", "description": "Authentication failure"}
        assert mock_statsd.incr.called_with('oauth.authorization.failure')


class TestGetServicesByUser:
    def test_should_return_200(self, client, sample_user):
        json_resp = client.get('/auth/my-services/{}'.format(sample_user.id))

        assert json_resp.status_code == 200
