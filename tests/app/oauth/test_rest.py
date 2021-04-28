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


class TestLogin:

    def test_should_return_501_if_toggle_is_disabled(self, client, toggle_disabled):
        response = client.get('/login')

        assert response.status_code == 501

    def test_should_redirect_to_github_if_toggle_is_enabled(self, client, toggle_enabled):
        response = client.get('/login')

        assert response.status_code == 302
        assert 'https://github.com/login/oauth/authorize' in response.location


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

    def test_should_redirect_to_login_failure_if_emails_do_not_contain_verified_thoughtworks_address(
            self,
            client,
            notify_api,
            toggle_enabled,
            mocker
    ):
        mocker.patch('app.oauth.rest.oauth_registry.github.authorize_access_token')
        github_user_emails = [
            {
                "email": "some.user@not-thoughtworks.com",
                "verified": True,
                "primary": True,
                "visibility": "public"
            },
            {
                "email": "some.user@thoughtworks.com",
                "verified": False,
                "primary": False,
                "visibility": "public"
            }
        ]
        mocker.patch(
            'app.oauth.rest.oauth_registry.github.get',
            return_value=mocker.Mock(Response, json=mocker.Mock(return_value=github_user_emails))
        )

        with set_config_values(notify_api, {
            'UI_HOST_NAME': 'https://some-ui-host-name.com',
            'JWT_ACCESS_COOKIE_NAME': 'cookie-name'
        }):
            response = client.get('/authorize')

        assert response.status_code == 302
        assert 'https://some-ui-host-name.com/login/failure' in response.location

        assert not any(
            cookie.name == 'cookie-name' for cookie in client.cookie_jar
        )

    def test_should_redirect_to_ui_if_toggle_is_enabled_and_access_token_is_authorized(
            self,
            client,
            notify_api,
            toggle_enabled,
            mocker
    ):
        mocker.patch('app.oauth.rest.oauth_registry.github.authorize_access_token')
        github_user_emails = [
            {
                "email": "some.user@thoughtworks.com",
                "verified": True,
                "primary": True,
                "visibility": "public"
            }
        ]
        mocker.patch(
            'app.oauth.rest.oauth_registry.github.get',
            return_value=mocker.Mock(Response, json=mocker.Mock(return_value=github_user_emails))
        )

        found_user = User()
        mocker.patch('app.oauth.rest.get_user_by_email', return_value=found_user)
        create_access_token = mocker.patch('app.oauth.rest.create_access_token', return_value='some-access-token-value')

        with set_config_values(notify_api, {
            'UI_HOST_NAME': 'https://some-ui-host-name.com',
            'JWT_ACCESS_COOKIE_NAME': 'cookie-name'
        }):
            response = client.get('/authorize')

        create_access_token.assert_called_with(identity=found_user)

        assert response.status_code == 302
        assert 'https://some-ui-host-name.com' in response.location

        assert any(
            cookie.name == 'cookie-name' and cookie.value == 'some-access-token-value' for cookie in client.cookie_jar
        )


class TestRedeemToken:

    def test_should_return_501_if_toggle_is_disabled(self, client, toggle_disabled):
        response = client.get('/redeem-token')

        assert response.status_code == 501

    @pytest.mark.parametrize('exception', [NoAuthorizationError, ExpiredSignatureError])
    def test_should_return_401_if_cookie_verification_fails(self, client, toggle_enabled, mocker, exception):
        mocker.patch('app.oauth.rest.verify_jwt_in_request', side_effect=exception)
        response = client.get('/redeem-token')

        assert response.status_code == 401

    def test_should_return_cookie_in_body(self, client, toggle_enabled, mocker, notify_api):
        mocker.patch('app.oauth.rest.verify_jwt_in_request', side_effect=None)

        client.set_cookie('test', 'cookie-name', 'some-cookie-value')

        with set_config_values(notify_api, {
            'JWT_ACCESS_COOKIE_NAME': 'cookie-name'
        }):
            response = client.get('/redeem-token')

        assert response.status_code == 200
        assert response.json.get('data') == 'some-cookie-value'

    def test_should_set_cors_headers(self, client, toggle_enabled, mocker, notify_api):
        mocker.patch('app.oauth.rest.verify_jwt_in_request', side_effect=None)

        with set_config_values(notify_api, {
            'UI_HOST_NAME': 'https://some-ui-host-name.com'
        }):
            response = client.get('/redeem-token')

        assert response.access_control_allow_credentials
        assert response.access_control_allow_origin == 'https://some-ui-host-name.com'
