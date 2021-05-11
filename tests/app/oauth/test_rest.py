import os

import pytest
from flask_jwt_extended.exceptions import NoAuthorizationError
from jwt import ExpiredSignatureError
from requests import Response

from app.feature_flags import FeatureFlag
from app.models import User
from tests.conftest import set_config_values


def mock_toggle(mocker, enabled: str) -> None:
    mocker.patch.dict(os.environ, {FeatureFlag.GITHUB_LOGIN_ENABLED.value: enabled})


@pytest.fixture
def toggle_disabled(mocker):
    mock_toggle(mocker, 'False')


@pytest.fixture
def toggle_enabled(mocker):
    mock_toggle(mocker, 'True')


@pytest.fixture
def identity_provider_authorization_url():
    return "https://github.com/login/oauth/authorize"


@pytest.fixture
def cookie_config():
    return {
        'UI_HOST_NAME': 'https://some-ui-host-name.com',
        'JWT_ACCESS_COOKIE_NAME': 'cookie-name'
    }


class TestLogin:

    def test_should_return_501_if_toggle_is_disabled(self, client, toggle_disabled):
        response = client.get('/login')

        assert response.status_code == 501

    def test_should_redirect_to_github_if_toggle_is_enabled(
            self, client, toggle_enabled, identity_provider_authorization_url
    ):
        response = client.get('/login')

        assert response.status_code == 302
        assert identity_provider_authorization_url in response.location


class TestAuthorize:
    github_user_emails = [
        {
            "email": "some.user@thoughtworks.com",
            "verified": True,
            "primary": True,
            "visibility": "public"
        }
    ]

    def test_should_return_501_if_toggle_is_disabled(self, client, toggle_disabled):
        response = client.get('/authorize')

        assert response.status_code == 501

    @pytest.mark.parametrize('status_code', [403, 404])
    def test_should_redirect_to_login_failure_if_organization_membership_verification_fails(
            self,
            client,
            notify_api,
            toggle_enabled,
            mocker,
            status_code,
            cookie_config
    ):
        mocker.patch('app.oauth.rest.oauth_registry.github.authorize_access_token')
        github_organization_membership_response = mocker.Mock(Response, status_code=status_code)

        mocker.patch(
            'app.oauth.rest.oauth_registry.github.get',
            return_value=github_organization_membership_response
        )

        with set_config_values(notify_api, cookie_config):
            response = client.get('/authorize')

        assert response.status_code == 302
        assert f"{cookie_config['UI_HOST_NAME']}/login/failure" in response.location

        assert not any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME'] for cookie in client.cookie_jar
        )

    def test_should_redirect_to_ui_if_user_is_member_of_va_organization(
            self,
            client,
            notify_api,
            toggle_enabled,
            mocker,
            cookie_config
    ):
        mocker.patch('app.oauth.rest.oauth_registry.github.authorize_access_token')

        github_organization_membership_response = mocker.Mock(Response, status_code=200)

        github_user_emails = [
            {
                "email": "some.user@thoughtworks.com",
                "verified": True,
                "primary": True,
                "visibility": "public"
            }
        ]
        github_user_emails_response = mocker.Mock(Response, json=mocker.Mock(return_value=github_user_emails))
        mocker.patch(
            'app.oauth.rest.oauth_registry.github.get',
            side_effect=[github_organization_membership_response, github_user_emails_response]
        )

        found_user = User()
        mocker.patch('app.oauth.rest.get_user_by_email', return_value=found_user)
        create_access_token = mocker.patch('app.oauth.rest.create_access_token', return_value='some-access-token-value')

        with set_config_values(notify_api, cookie_config):
            response = client.get('/authorize')

        create_access_token.assert_called_with(identity=found_user)

        assert response.status_code == 302
        assert cookie_config['UI_HOST_NAME'] in response.location

        assert any(
            cookie.name == cookie_config['JWT_ACCESS_COOKIE_NAME']
            and cookie.value == 'some-access-token-value'
            for cookie in client.cookie_jar
        )


class TestRedeemToken:

    def test_should_return_501_if_toggle_is_disabled(self, client, toggle_disabled):
        response = client.get('/redeem-token')

        assert response.status_code == 501

    @pytest.mark.parametrize('exception', [NoAuthorizationError, ExpiredSignatureError])
    def test_should_return_401_if_cookie_verification_fails(
            self, client, toggle_enabled, mocker, exception
    ):
        mocker.patch('app.oauth.rest.verify_jwt_in_request', side_effect=exception)
        response = client.get('/redeem-token')

        assert response.status_code == 401

    def test_should_return_cookie_in_body(
            self, client, toggle_enabled, mocker, notify_api, cookie_config
    ):
        mocker.patch('app.oauth.rest.verify_jwt_in_request', side_effect=None)

        expected_cookie_value = 'some-cookie-value'
        client.set_cookie('test',
                          cookie_config['JWT_ACCESS_COOKIE_NAME'],
                          expected_cookie_value)

        with set_config_values(notify_api,
                               {'JWT_ACCESS_COOKIE_NAME': cookie_config['JWT_ACCESS_COOKIE_NAME']}
                               ):
            response = client.get('/redeem-token')

        assert response.status_code == 200
        assert response.json.get('data') == expected_cookie_value

    def test_should_set_cors_headers(self, client, toggle_enabled, mocker, notify_api, cookie_config):
        mocker.patch('app.oauth.rest.verify_jwt_in_request', side_effect=None)

        with set_config_values(notify_api, {
            'UI_HOST_NAME': cookie_config['UI_HOST_NAME']
        }):
            response = client.get('/redeem-token')

        assert response.access_control_allow_credentials
        assert response.access_control_allow_origin == cookie_config['UI_HOST_NAME']
