import pytest
from typing import Dict
from requests import Response

from app.feature_flags import FeatureFlag
from app.oauth.exceptions import (
    OAuthException,
    InsufficientGithubScopesException,
)
from app.oauth.rest import make_github_get_request
from tests.conftest import set_config_values
from tests.app.factories.feature_flag import mock_feature_flag

cookie_config = {
    'UI_HOST_NAME': 'https://some-ui-host-name.com',
    'JWT_ACCESS_COOKIE_NAME': 'cookie-name',
    'SESSION_COOKIE_SECURE': True,
}


@pytest.fixture(scope='module', autouse=True)
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
    'url': 'https://api.github.com/orgs/department-of-veterans-affairs/memberships/some-user',
    'state': 'pending',
    'role': 'user',
    'organization_url': 'https://api.github.com/orgs/department-of-veterans-affairs',
    'organization': {
        'login': 'department-of-veterans-affairs',
        'id': 1,
        'node_id': 'blahblahblah',
        'url': 'https://api.github.com/orgs/department-of-veterans-affairs',
        'repos_url': 'https://api.github.com/orgs/department-of-veterans-affairs/repos',
        'events_url': 'https://api.github.com/orgs/department-of-veterans-affairs/events',
        'hooks_url': 'https://api.github.com/orgs/department-of-veterans-affairs/hooks',
        'issues_url': 'https://api.github.com/orgs/department-of-veterans-affairs/issues',
        'members_url': 'https://api.github.com/orgs/department-of-veterans-affairs/members/someuser',
        'public_members_url': 'https://api.github.com/orgs/department-of-veterans-affairs/public_members/someuser',
        'avatar_url': 'https://github.com/images/error/octocat_happy.gif',
        'description': 'Some organization',
    },
    'user': {
        'login': 'someuser',
        'id': 1,
        'node_id': 'MDQ6VXNlcjE=',
        'avatar_url': 'https://github.com/images/error/octocat_happy.gif',
        'gravatar_id': '',
        'url': 'https://api.github.com/users/someuser',
        'html_url': 'https://github.com/someuser',
        'followers_url': 'https://api.github.com/users/someuser/followers',
        'following_url': 'https://api.github.com/users/someuser/following{/other_user}',
        'gists_url': 'https://api.github.com/users/someuser/gists{/gist_id}',
        'starred_url': 'https://api.github.com/users/someuser/starred{/owner}{/repo}',
        'subscriptions_url': 'https://api.github.com/users/someuser/subscriptions',
        'organizations_url': 'https://api.github.com/users/someuser/orgs',
        'repos_url': 'https://api.github.com/users/someuser/repos',
        'events_url': 'https://api.github.com/users/someuser/events{/privacy}',
        'received_events_url': 'https://api.github.com/users/someuser/received_events',
        'type': 'User',
        'site_admin': False,
    },
}


github_user = {
    'login': 'someuser',
    'id': 1,
    'node_id': 'MDQ6VXNlcjE=',
    'avatar_url': 'https://github.com/images/error/octocat_happy.gif',
    'gravatar_id': '',
    'url': 'https://api.github.com/users/someuser',
    'html_url': 'https://github.com/someuser',
    'followers_url': 'https://api.github.com/users/someuser/followers',
    'following_url': 'https://api.github.com/users/someuser/following{/other_user}',
    'gists_url': 'https://api.github.com/users/someuser/gists{/gist_id}',
    'starred_url': 'https://api.github.com/users/someuser/starred{/owner}{/repo}',
    'subscriptions_url': 'https://api.github.com/someuser/octocat/subscriptions',
    'organizations_url': 'https://api.github.com/someuser/octocat/orgs',
    'repos_url': 'https://api.github.com/users/someuser/repos',
    'events_url': 'https://api.github.com/users/someuser/events{/privacy}',
    'received_events_url': 'https://api.github.com/users/someuser/received_events',
    'type': 'User',
    'site_admin': False,
    'name': 'monalisa someuser',
    'company': 'GitHub',
    'blog': 'https://github.com/blog',
    'location': 'San Francisco',
    'email': 'octocat@github.com',
    'hireable': False,
    'bio': 'There once was...',
    'twitter_username': 'monatheoctocat',
    'public_repos': 2,
    'public_gists': 1,
    'followers': 20,
    'following': 0,
    'created_at': '2008-01-14T04:33:35Z',
    'updated_at': '2008-01-14T04:33:35Z',
    'private_gists': 81,
    'total_private_repos': 100,
    'owned_private_repos': 100,
    'disk_usage': 10000,
    'collaborators': 8,
    'two_factor_authentication': True,
    'plan': {'name': 'Medium', 'space': 400, 'private_repos': 20, 'collaborators': 0},
}


github_user_emails = [
    {'email': 'some.user@thoughtworks.com', 'verified': True, 'primary': True, 'visibility': 'public'}
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
    mocker.patch('app.oauth.rest.make_github_get_request', side_effect=lambda endpoint, _token: response_map[endpoint])


@pytest.fixture(autouse=True)
def mock_default_github_user_responses(mocker):
    mock_github_responses(mocker)


@pytest.fixture(autouse=True)
def mock_github_authorize_access_token(mocker):
    return mocker.patch('app.oauth.rest.oauth_registry.github.authorize_access_token')


@pytest.fixture(autouse=True)
def mock_statsd(mocker):
    return mocker.patch('app.oauth.rest.statsd_client')


id_token = 'id_token'
tokens = {
    'token_type': 'Bearer',
    'expires_in': 3600,
    'scope': 'openid profile email',
    'id_token': id_token,
    'expires_at': 1568044390,
}
va_sso_user_info = {
    'fediamMVIICN': '1010031911V591044',
    'nonce': '123',
    'email': 'FIRST.LASTNAME@VA.GOV',
    'iat': 1568040790,
    'iss': 'https://sqa.fed.eauth.va.gov/oauthi/sps/oauth/oauth20/metadata/ISAMOP',
    'at_hash': 'bFo9KMdkW5ov7eBAWjfHhg',
    'sub': '1010031911',
    'fediamVAUID': '22128',
    'family_name': 'LASTNAME',
    'fediamadSamAccountName': 'VHAISWSMITRE',
    'given_name': 'FIRST',
    'fediamsecid': '1010031911',
    'exp': 1568044390,
    'aud': 'ampl_gui',
}


@pytest.fixture(autouse=True)
def mock_va_sso_authorize_access_token(mocker):
    return mocker.patch('app.oauth.rest.oauth_registry.va_sso.authorize_access_token', return_value=tokens)


@pytest.fixture(autouse=True)
def mock_va_sso_parse_id_token(mocker):
    return mocker.patch('app.oauth.rest.oauth_registry.va_sso.parse_id_token', return_value=va_sso_user_info)


class TestMakeGithubGetRequest:
    def test_should_raise_exception_if_304_from_github_get(self, client, notify_api, mocker):
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
    def test_should_raise_http_error_if_error_from_github_get(self, client, notify_api, mocker, status_code):
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

    def test_should_raise_insufficient_github_scopes_exception_if_missing_scopes(self, client, notify_api, mocker):
        github_get_user_resp = mocker.Mock(Response, status_code=200, headers={'X-OAuth-Scopes': 'read:org'})

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
