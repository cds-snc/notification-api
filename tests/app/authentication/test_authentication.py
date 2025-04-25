"""
Many tests in this module take "self" and the fixture "client" as parameters which appear unused.
"self" is used by tests in the TestRequiresUserInService class.  Without these parameters, the
tests error with, "Working outside of request context."
"""

import jwt
import pytest
import time
from app import api_user
from app.authentication.auth import (
    AuthError,
    validate_admin_auth,
    validate_service_api_key_auth,
    requires_admin_auth_or_user_in_service,
    requires_user_in_service_or_admin,
)
from app.constants import PERMISSION_LIST, SERVICE_PERMISSION_TYPES
from app.dao.api_key_dao import get_unsigned_secrets
from app.dao.permissions_dao import permission_dao
from app.models import Permission
from app.service.service_data import ServiceDataApiKey
from flask import json, current_app, request
from flask_jwt_extended import create_access_token
from freezegun import freeze_time
from jwt import ExpiredSignatureError
from notifications_python_client.authentication import create_jwt_token
from tests.conftest import set_config, set_config_values
from uuid import uuid4


@pytest.mark.parametrize('auth_fn', [validate_service_api_key_auth, validate_admin_auth])
def test_should_not_allow_request_with_no_token(client, auth_fn):
    request.headers = {}
    with pytest.raises(AuthError) as exc:
        auth_fn()
    assert exc.value.short_message == 'Unauthorized, authentication token must be provided'


@pytest.mark.parametrize('auth_fn', [validate_service_api_key_auth, validate_admin_auth])
def test_should_not_allow_request_with_incorrect_header(client, auth_fn):
    request.headers = {'Authorization': 'Basic 1234'}
    with pytest.raises(AuthError) as exc:
        auth_fn()
    assert exc.value.short_message == 'Unauthorized, authentication bearer scheme must be used'


@pytest.mark.parametrize('auth_fn', [validate_service_api_key_auth, validate_admin_auth])
def test_should_not_allow_request_with_incorrect_token(client, auth_fn):
    request.headers = {'Authorization': 'Bearer 1234'}
    with pytest.raises(AuthError) as exc:
        auth_fn()
    assert exc.value.short_message == 'Invalid token: signature, api token is not valid'


@pytest.mark.parametrize('auth_fn', [validate_service_api_key_auth, validate_admin_auth])
def test_should_not_allow_request_with_no_iss(client, auth_fn):
    # code copied from notifications_python_client.authentication.py::create_jwt_token
    headers = {'typ': 'JWT', 'alg': 'HS256'}

    claims = {
        # 'iss': not provided
        'iat': int(time.time())
    }

    token = jwt.encode(payload=claims, key=str(uuid4()), headers=headers)

    request.headers = {'Authorization': 'Bearer {}'.format(token)}
    with pytest.raises(AuthError) as exc:
        auth_fn()
    assert exc.value.short_message == 'Invalid token: iss field not provided'


def test_auth_should_not_allow_request_with_no_iat(client, sample_user_service_api_key):
    _, service, _ = sample_user_service_api_key
    iss = str(service.id)

    headers = {
        'typ': 'JWT',
        'alg': 'HS256',
    }

    claims = {
        'iss': iss,
    }

    token = jwt.encode(payload=claims, key=str(uuid4()), headers=headers)

    request.headers = {'Authorization': 'Bearer {}'.format(token)}
    with pytest.raises(AuthError) as exc:
        validate_service_api_key_auth()
    assert exc.value.short_message == 'Invalid token: signature, api token not found'


def test_admin_auth_should_not_allow_request_with_no_iat(client):
    iss = current_app.config['ADMIN_CLIENT_USER_NAME']

    # code copied from notifications_python_client.authentication.py::create_jwt_token
    headers = {'typ': 'JWT', 'alg': 'HS256'}

    claims = {
        'iss': iss
        # 'iat': not provided
    }

    token = jwt.encode(payload=claims, key=str(uuid4()), headers=headers)

    request.headers = {'Authorization': 'Bearer {}'.format(token)}
    with pytest.raises(AuthError) as exc:
        validate_admin_auth()
    assert exc.value.short_message == 'Invalid token: signature, api token is not valid'


def test_should_not_allow_invalid_secret(client, sample_notification, sample_user_service_api_key):
    _, service, _ = sample_user_service_api_key

    token = create_jwt_token(secret='not-so-secret', client_id=str(service.id))

    notification = sample_notification()
    response = client.get(f'/v2/notifications/{notification.id}', headers={'Authorization': f'Bearer {token}'})

    assert response.status_code == 403
    data = json.loads(response.get_data())
    assert data['errors'][0]['message'] == 'Invalid token: signature, api token not found'


@pytest.mark.parametrize('scheme', ['bearer', 'Bearer'])
def test_should_allow_valid_token(client, sample_notification, sample_template, sample_user_service_api_key, scheme):
    _, _, api_key = sample_user_service_api_key

    token = __create_token(api_key.service_id)
    template = sample_template(service=api_key.service)
    notification = sample_notification(template=template, api_key=api_key)

    response = client.get(f'/v2/notifications/{notification.id}', headers={'Authorization': f'{scheme} {token}'})
    assert response.status_code == 200


def test_should_not_allow_service_id_that_is_not_uuid(client, sample_notification, sample_user_service_api_key):
    _, service, _ = sample_user_service_api_key

    token = create_jwt_token(secret=get_unsigned_secrets(service.id)[0], client_id=str('not-a-valid-uuid'))
    notification = sample_notification()

    response = client.get(f'/v2/notifications/{notification.id}', headers={'Authorization': f'Bearer {token}'})

    assert response.status_code == 403
    assert response.get_json()['errors'][0]['message'] == 'Invalid token: service id is not the right data type'


def test_should_allow_valid_token_for_request_with_path_params_for_public_url(
    client, sample_notification, sample_template, sample_user_service_api_key
):
    _, service, _ = sample_user_service_api_key

    token = __create_token(service.id)
    template = sample_template(service=service)
    notification = sample_notification(template=template)

    response = client.get(f'/v2/notifications/{notification.id}', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200


def test_should_allow_valid_token_for_request_with_path_params_for_admin_url(client):
    token = create_jwt_token(current_app.config['ADMIN_CLIENT_SECRET'], current_app.config['ADMIN_CLIENT_USER_NAME'])
    response = client.get('/service', headers={'Authorization': 'Bearer {}'.format(token)})
    assert response.status_code == 200


def test_should_allow_valid_token_when_service_has_multiple_keys(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
    sample_user_service_api_key,
):
    _, service, api_key1 = sample_user_service_api_key
    api_key2 = sample_api_key(service)

    assert api_key1.service == api_key2.service, 'The api keys should both be associated with the same service.'

    token = __create_token(service.id)
    template = sample_template(service=service)
    notification = sample_notification(template=template)

    response = client.get(f'/v2/notifications/{notification.id}', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200


def test_authentication_passes_when_service_has_multiple_keys_some_expired(
    client, sample_api_key, sample_user_service_api_key, sample_notification, sample_template
):
    _, service, api_key = sample_user_service_api_key
    expired_api_key = sample_api_key(service, expired=True)

    assert api_key.service == expired_api_key.service, 'The api keys should both be associated with the same service.'

    token = create_jwt_token(secret=api_key.secret, client_id=str(service.id))
    template = sample_template(service=service)
    notification = sample_notification(template=template)

    response = client.get(f'/v2/notifications/{notification.id}', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200


def test_authentication_returns_token_expired_when_service_uses_expired_key_and_has_multiple_keys(
    client, sample_api_key, sample_user_service_api_key
):
    _, service, api_key = sample_user_service_api_key
    expired_api_key = sample_api_key(service, expired=True)

    assert api_key.service == expired_api_key.service, 'The api keys should both be associated with the same service.'

    token = create_jwt_token(expired_api_key.secret, client_id=str(service.id))

    request.headers = {'Authorization': 'Bearer {}'.format(token)}
    with pytest.raises(AuthError) as exc:
        validate_service_api_key_auth()
    assert exc.value.short_message == 'Invalid token: API key revoked'
    assert exc.value.service_id == service.id
    assert exc.value.api_key_id == expired_api_key.id


def test_authentication_returns_error_when_admin_client_has_no_secrets(client):
    api_secret = current_app.config.get('ADMIN_CLIENT_SECRET')
    api_service_id = current_app.config.get('ADMIN_CLIENT_USER_NAME')

    token = create_jwt_token(secret=api_secret, client_id=api_service_id)

    with set_config(client.application, 'ADMIN_CLIENT_SECRET', ''):
        response = client.get('/service', headers={'Authorization': 'Bearer {}'.format(token)})

    assert response.status_code == 403
    error_message = json.loads(response.get_data())
    assert error_message['message'] == 'Invalid token: signature, api token is not valid'


def test_authentication_returns_error_when_admin_client_secret_is_invalid(client):
    api_secret = current_app.config.get('ADMIN_CLIENT_SECRET')

    token = create_jwt_token(secret=api_secret, client_id=current_app.config.get('ADMIN_CLIENT_USER_NAME'))

    current_app.config['ADMIN_CLIENT_SECRET'] = 'something-wrong'

    response = client.get('/service', headers={'Authorization': 'Bearer {}'.format(token)})

    assert response.status_code == 403
    error_message = json.loads(response.get_data())
    assert error_message['message'] == 'Invalid token: signature, api token is not valid'
    current_app.config['ADMIN_CLIENT_SECRET'] = api_secret


def test_authentication_returns_error_when_service_doesnt_exit(
    client, sample_user_service_api_key, sample_notification, sample_template
):
    _, service, api_key = sample_user_service_api_key

    # Use the UUIDs of sample_api_key, but assign them to the wrong parameters.
    token = create_jwt_token(secret=str(service.id), client_id=str(api_key.id))

    template = sample_template(service=service)
    notification = sample_notification(template=template)
    response = client.get(f'/v2/notifications/{notification.id}', headers={'Authorization': f'Bearer {token}'})

    assert response.status_code == 403
    error_message = json.loads(response.get_data())
    assert error_message['errors'][0]['message'] == 'Invalid token: service not found'


def test_authentication_returns_error_when_service_inactive(
    client,
    sample_api_key,
    sample_user,
    sample_service,
    sample_notification,
    sample_template,
):
    user = sample_user()
    service = sample_service(user=user, active=False)
    assert service.created_by == user
    assert not service.active
    api_key = sample_api_key(service)
    assert api_key in service.api_keys

    token = create_jwt_token(secret=str(api_key.secret), client_id=str(service.id))

    template = sample_template(service=service)
    notification = sample_notification(template=template)
    response = client.get(f'/v2/notifications/{notification.id}', headers={'Authorization': f'Bearer {token}'})

    assert response.status_code == 403
    error_message = json.loads(response.get_data())
    assert error_message['errors'][0]['message'] == 'Invalid token: service is archived'


def test_authentication_returns_error_when_service_has_no_secrets(client, sample_user_service_api_key, fake_uuid):
    _, service, _ = sample_user_service_api_key

    token = create_jwt_token(secret=fake_uuid, client_id=str(service.id))

    request.headers = {'Authorization': 'Bearer {}'.format(token)}
    with pytest.raises(AuthError) as exc:
        validate_service_api_key_auth()
    assert 'Invalid token' in exc.value.short_message
    assert exc.value.service_id == service.id


def test_should_attach_the_current_api_key_to_current_app(
    notify_api, sample_user_service_api_key, sample_template, sample_notification
):
    _, service, api_key = sample_user_service_api_key

    with notify_api.test_request_context(), notify_api.test_client() as client:
        token = create_jwt_token(secret=api_key.secret, client_id=str(service.id))

        template = sample_template(service=service)
        notification = sample_notification(template=template)
        response = client.get(f'/v2/notifications/{notification.id}', headers={'Authorization': f'Bearer {token}'})

        assert response.status_code == 200

        # api_user is a ServiceDataApiKey instance assigned globally after a service is authenticated.
        assert isinstance(api_user, ServiceDataApiKey)
        assert api_user.id == api_key.id


def test_should_return_403_when_token_is_expired(client, sample_user_service_api_key):
    _, service, api_key = sample_user_service_api_key

    with freeze_time('2001-01-01T12:00:00'):
        token = create_jwt_token(secret=api_key.secret, client_id=str(service.id))
    with freeze_time('2001-01-01T12:00:40'):
        with pytest.raises(AuthError) as exc:
            request.headers = {'Authorization': 'Bearer {}'.format(token)}
            validate_service_api_key_auth()
    assert exc.value.short_message == 'Error: Your system clock must be accurate to within 30 seconds'
    assert exc.value.service_id == service.id
    assert exc.value.api_key_id == api_key.id


def __create_token(service_id):
    return create_jwt_token(secret=get_unsigned_secrets(service_id)[0], client_id=str(service_id))


@pytest.mark.parametrize(
    'check_proxy_header, header_value, expected_status',
    [
        (True, 'key_1', 200),
        (True, 'wrong_key', 200),
        (False, 'key_1', 200),
        (False, 'wrong_key', 200),
    ],
)
def test_proxy_key_non_auth_endpoint(notify_api, check_proxy_header, header_value, expected_status):
    # Test takes 2-5 seconds to run when done in parallel
    with set_config_values(
        notify_api,
        {
            'ROUTE_SECRET_KEY_1': 'key_1',
            'ROUTE_SECRET_KEY_2': '',
            'CHECK_PROXY_HEADER': check_proxy_header,
        },
    ):
        with notify_api.test_client() as client:
            response = client.get(
                path='/_status',
                headers=[
                    ('X-Custom-Forwarder', header_value),
                ],
            )
        assert response.status_code == expected_status


@pytest.mark.parametrize(
    'check_proxy_header, header_value, expected_status',
    [
        (True, 'key_1', 200),
        (True, 'wrong_key', 403),
        (False, 'key_1', 200),
        (False, 'wrong_key', 200),
    ],
)
def test_proxy_key_on_admin_auth_endpoint(notify_api, check_proxy_header, header_value, expected_status):
    token = create_jwt_token(current_app.config['ADMIN_CLIENT_SECRET'], current_app.config['ADMIN_CLIENT_USER_NAME'])

    with set_config_values(
        notify_api,
        {
            'ROUTE_SECRET_KEY_1': 'key_1',
            'ROUTE_SECRET_KEY_2': '',
            'CHECK_PROXY_HEADER': check_proxy_header,
        },
    ):
        with notify_api.test_client() as client:
            response = client.get(
                path='/service',
                headers=[('X-Custom-Forwarder', header_value), ('Authorization', 'Bearer {}'.format(token))],
            )
        assert response.status_code == expected_status


class TestRequiresUserInService:
    def test_accepts_jwt_for_user_in_service(self, client, sample_user_service_api_key):
        user, service, _ = sample_user_service_api_key

        @requires_user_in_service_or_admin()
        def endpoint_that_requires_user_in_service():
            pass

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_user_in_service()

    def test_rejects_jwt_for_user_not_in_service(self, client, sample_user_service_api_key):
        user, service, _ = sample_user_service_api_key

        @requires_user_in_service_or_admin()
        def endpoint_that_requires_user_in_service():
            pass

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        assert len(service.users) == 1 and service.users[0] == user
        service.users.clear()

        with pytest.raises(AuthError) as error:
            endpoint_that_requires_user_in_service()

        assert error.value.code == 403

    def test_propagates_error_when_bearer_token_expired(self, client, mocker, sample_user_service_api_key):
        user, service, _ = sample_user_service_api_key

        @requires_user_in_service_or_admin()
        def endpoint_that_requires_user_in_service():
            pass

        token = create_access_token(identity=user)
        mocker.patch('app.authentication.auth.verify_jwt_in_request', side_effect=ExpiredSignatureError)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        with pytest.raises(ExpiredSignatureError):
            endpoint_that_requires_user_in_service()

    @pytest.mark.parametrize('required_permission', PERMISSION_LIST)
    def test_accepts_jwt_with_permission_for_service(
        self, notify_db_session, client, required_permission, sample_user_service_api_key
    ):
        # This one tests a user with valid permissions
        # The PERMISSION_LIST is for users to be able to do things with services
        user, service, _ = sample_user_service_api_key
        permission_list = [Permission(service_id=service.id, user_id=user.id, permission=required_permission)]
        permission_dao.set_user_service_permission(user, service, permission_list, _commit=True, replace=True)

        @requires_user_in_service_or_admin(required_permission=required_permission)
        def endpoint_that_requires_permission_for_service():
            pass

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_permission_for_service()

    def test_rejects_jwt_without_permission_for_service(self, client, sample_user_service_api_key):
        user, service, _ = sample_user_service_api_key

        @requires_user_in_service_or_admin(required_permission='some-required-permission')
        def endpoint_that_requires_permission_for_service():
            pass

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        with pytest.raises(AuthError) as error:
            endpoint_that_requires_permission_for_service()

        assert error.value.code == 403

    def test_accepts_jwt_for_platform_admin(self, client, sample_user, sample_user_service_api_key):
        user, service, _ = sample_user_service_api_key
        admin_user = sample_user(platform_admin=True)

        assert admin_user.platform_admin
        assert user in service.users
        assert admin_user not in service.users, 'Admin users should not need to be assigned to a service.'

        @requires_user_in_service_or_admin()
        def endpoint_that_requires_user_in_service():
            pass

        token = create_access_token(identity=admin_user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_user_in_service()


class TestRequiresAdminAuthOrUserInService:
    @pytest.mark.parametrize('required_permission', SERVICE_PERMISSION_TYPES)
    def test_accepts_jwt_with_permission_for_service(
        self, notify_db_session, client, required_permission, sample_user, sample_service
    ):
        # This one tests the admin path
        admin_user = sample_user(platform_admin=True)
        service = sample_service(service_permissions=SERVICE_PERMISSION_TYPES)

        @requires_user_in_service_or_admin(required_permission=required_permission)
        def endpoint_that_requires_permission_for_service():
            pass

        token = create_access_token(identity=admin_user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_permission_for_service()

    def test_rejects_jwt_without_permission_for_service(self, client, sample_user_service_api_key):
        user, service, _ = sample_user_service_api_key

        @requires_admin_auth_or_user_in_service(required_permission='some-required-permission')
        def endpoint_that_requires_admin_auth_or_permission_for_service():
            pass

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        with pytest.raises(AuthError) as error:
            endpoint_that_requires_admin_auth_or_permission_for_service()

        assert error.value.code == 403

    @pytest.mark.parametrize('required_permission', PERMISSION_LIST)
    def test_accepts_admin_jwt(self, client, required_permission):
        @requires_admin_auth_or_user_in_service(required_permission=required_permission)
        def endpoint_that_requires_admin_auth_or_permission_for_service():
            pass

        token = create_jwt_token(
            current_app.config['ADMIN_CLIENT_SECRET'], current_app.config['ADMIN_CLIENT_USER_NAME']
        )

        request.view_args['service_id'] = 'some-service-id'
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_admin_auth_or_permission_for_service()

    def test_accepts_jwt_for_platform_admin(self, client, sample_user, sample_service):
        admin_user = sample_user(platform_admin=True)
        service = sample_service()
        assert admin_user.platform_admin

        @requires_user_in_service_or_admin()
        def endpoint_that_requires_user_in_service():
            pass

        token = create_access_token(identity=admin_user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_user_in_service()

    @pytest.mark.parametrize('required_permission', PERMISSION_LIST)
    def test_accepts_jwt_for_platform_admin_even_with_required_permissions(
        self, client, required_permission, sample_user, sample_service, set_user_as_admin
    ):
        # Create normal user and service with all permissions
        user = sample_user()
        service = sample_service(user=user, service_permissions=SERVICE_PERMISSION_TYPES)

        # Add required permission to user that is in the service
        permission_list = [Permission(service_id=service.id, user_id=user.id, permission=required_permission)]
        permission_dao.set_user_service_permission(user, service, permission_list, _commit=True, replace=True)

        # Upgrade user to admin
        admin_user = set_user_as_admin(user)

        # Assert admin is the same user and that they are still in the service
        assert admin_user.id == user.id
        assert admin_user.platform_admin
        assert admin_user in service.users

        @requires_user_in_service_or_admin(required_permission=required_permission)
        def endpoint_that_requires_permission_for_service():
            pass

        # Setup current_user to be the admin user
        token = create_access_token(identity=admin_user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        # Validate no errors
        endpoint_that_requires_permission_for_service()
