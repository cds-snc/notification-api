import jwt
import uuid
import time
from datetime import datetime

from flask_jwt_extended import create_access_token
from jwt import ExpiredSignatureError

from app.dao.services_dao import dao_add_user_to_service
from tests.app.db import create_user, create_service
from tests.conftest import set_config_values

import pytest
from flask import json, current_app, request
from freezegun import freeze_time
from notifications_python_client.authentication import create_jwt_token

from app import api_user
from app.dao.api_key_dao import get_unsigned_secrets, save_model_api_key, get_unsigned_secret, expire_api_key
from app.models import ApiKey, KEY_TYPE_NORMAL, PERMISSION_LIST, Permission
from app.authentication.auth import AuthError, validate_admin_auth, validate_service_api_key_auth, \
    requires_admin_auth_or_user_in_service, requires_user_in_service_or_admin

from tests.conftest import set_config


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
    headers = {
        "typ": 'JWT',
        "alg": 'HS256'
    }

    claims = {
        # 'iss': not provided
        'iat': int(time.time())
    }

    token = jwt.encode(payload=claims, key=str(uuid.uuid4()), headers=headers)

    request.headers = {'Authorization': 'Bearer {}'.format(token)}
    with pytest.raises(AuthError) as exc:
        auth_fn()
    assert exc.value.short_message == 'Invalid token: iss field not provided'


def test_auth_should_not_allow_request_with_no_iat(client, sample_api_key):
    iss = str(sample_api_key.service_id)
    # code copied from notifications_python_client.authentication.py::create_jwt_token
    headers = {
        "typ": 'JWT',
        "alg": 'HS256'
    }

    claims = {
        'iss': iss
        # 'iat': not provided
    }

    token = jwt.encode(payload=claims, key=str(uuid.uuid4()), headers=headers)

    request.headers = {'Authorization': 'Bearer {}'.format(token)}
    with pytest.raises(AuthError) as exc:
        validate_service_api_key_auth()
    assert exc.value.short_message == 'Invalid token: signature, api token not found'


def test_admin_auth_should_not_allow_request_with_no_iat(client, sample_api_key):
    iss = current_app.config['ADMIN_CLIENT_USER_NAME']

    # code copied from notifications_python_client.authentication.py::create_jwt_token
    headers = {
        "typ": 'JWT',
        "alg": 'HS256'
    }

    claims = {
        'iss': iss
        # 'iat': not provided
    }

    token = jwt.encode(payload=claims, key=str(uuid.uuid4()), headers=headers)

    request.headers = {'Authorization': 'Bearer {}'.format(token)}
    with pytest.raises(AuthError) as exc:
        validate_admin_auth()
    assert exc.value.short_message == 'Invalid token: signature, api token is not valid'


def test_should_not_allow_invalid_secret(client, sample_api_key):
    token = create_jwt_token(  # nosec
        secret="not-so-secret",
        client_id=str(sample_api_key.service_id))
    response = client.get(
        '/notifications',
        headers={'Authorization': "Bearer {}".format(token)}
    )
    assert response.status_code == 403
    data = json.loads(response.get_data())
    assert data['message'] == {"token": ['Invalid token: signature, api token not found']}


@pytest.mark.parametrize('scheme', ['bearer', 'Bearer'])
def test_should_allow_valid_token(client, sample_api_key, scheme):
    token = __create_token(sample_api_key.service_id)
    response = client.get('/notifications', headers={'Authorization': '{} {}'.format(scheme, token)})
    assert response.status_code == 200


def test_should_not_allow_service_id_that_is_not_the_wrong_data_type(client, sample_api_key):
    token = create_jwt_token(secret=get_unsigned_secrets(sample_api_key.service_id)[0],
                             client_id=str('not-a-valid-id'))
    response = client.get(
        '/notifications',
        headers={'Authorization': "Bearer {}".format(token)}
    )
    assert response.status_code == 403
    data = json.loads(response.get_data())
    assert data['message'] == {"token": ['Invalid token: service id is not the right data type']}


def test_should_allow_valid_token_for_request_with_path_params_for_public_url(client, sample_api_key):
    token = __create_token(sample_api_key.service_id)
    response = client.get('/notifications', headers={'Authorization': 'Bearer {}'.format(token)})
    assert response.status_code == 200


def test_should_allow_valid_token_for_request_with_path_params_for_admin_url(client):
    token = create_jwt_token(current_app.config['ADMIN_CLIENT_SECRET'], current_app.config['ADMIN_CLIENT_USER_NAME'])
    response = client.get('/service', headers={'Authorization': 'Bearer {}'.format(token)})
    assert response.status_code == 200


def test_should_allow_valid_token_when_service_has_multiple_keys(client, sample_api_key):
    data = {'service': sample_api_key.service,
            'name': 'some key name',
            'created_by': sample_api_key.created_by,
            'key_type': KEY_TYPE_NORMAL
            }
    api_key = ApiKey(**data)
    save_model_api_key(api_key)
    token = __create_token(sample_api_key.service_id)
    response = client.get(
        '/notifications'.format(str(sample_api_key.service_id)),
        headers={'Authorization': 'Bearer {}'.format(token)})
    assert response.status_code == 200


def test_authentication_passes_when_service_has_multiple_keys_some_expired(
        client,
        sample_api_key):
    expired_key_data = {'service': sample_api_key.service,
                        'name': 'expired_key',
                        'expiry_date': datetime.utcnow(),
                        'created_by': sample_api_key.created_by,
                        'key_type': KEY_TYPE_NORMAL
                        }
    expired_key = ApiKey(**expired_key_data)
    save_model_api_key(expired_key)
    another_key = {'service': sample_api_key.service,
                   'name': 'another_key',
                   'created_by': sample_api_key.created_by,
                   'key_type': KEY_TYPE_NORMAL
                   }
    api_key = ApiKey(**another_key)
    save_model_api_key(api_key)
    token = create_jwt_token(
        secret=get_unsigned_secret(api_key.id),
        client_id=str(sample_api_key.service_id))
    response = client.get(
        '/notifications',
        headers={'Authorization': 'Bearer {}'.format(token)})
    assert response.status_code == 200


def test_authentication_returns_token_expired_when_service_uses_expired_key_and_has_multiple_keys(client,
                                                                                                  sample_api_key):
    expired_key = {'service': sample_api_key.service,
                   'name': 'expired_key',
                   'created_by': sample_api_key.created_by,
                   'key_type': KEY_TYPE_NORMAL
                   }
    expired_api_key = ApiKey(**expired_key)
    save_model_api_key(expired_api_key)
    another_key = {'service': sample_api_key.service,
                   'name': 'another_key',
                   'created_by': sample_api_key.created_by,
                   'key_type': KEY_TYPE_NORMAL
                   }
    api_key = ApiKey(**another_key)
    save_model_api_key(api_key)
    token = create_jwt_token(
        secret=get_unsigned_secret(expired_api_key.id),
        client_id=str(sample_api_key.service_id))
    expire_api_key(service_id=sample_api_key.service_id, api_key_id=expired_api_key.id)
    request.headers = {'Authorization': 'Bearer {}'.format(token)}
    with pytest.raises(AuthError) as exc:
        validate_service_api_key_auth()
    assert exc.value.short_message == 'Invalid token: API key revoked'
    assert exc.value.service_id == expired_api_key.service_id
    assert exc.value.api_key_id == expired_api_key.id


def test_authentication_returns_error_when_admin_client_has_no_secrets(client):
    api_secret = current_app.config.get('ADMIN_CLIENT_SECRET')
    api_service_id = current_app.config.get('ADMIN_CLIENT_USER_NAME')
    token = create_jwt_token(
        secret=api_secret,
        client_id=api_service_id
    )
    with set_config(client.application, 'ADMIN_CLIENT_SECRET', ''):
        response = client.get(
            '/service',
            headers={'Authorization': 'Bearer {}'.format(token)})
    assert response.status_code == 403
    error_message = json.loads(response.get_data())
    assert error_message['message'] == {"token": ["Invalid token: signature, api token is not valid"]}


def test_authentication_returns_error_when_admin_client_secret_is_invalid(client):
    api_secret = current_app.config.get('ADMIN_CLIENT_SECRET')
    token = create_jwt_token(
        secret=api_secret,
        client_id=current_app.config.get('ADMIN_CLIENT_USER_NAME')
    )
    current_app.config['ADMIN_CLIENT_SECRET'] = 'something-wrong'
    response = client.get(
        '/service',
        headers={'Authorization': 'Bearer {}'.format(token)})
    assert response.status_code == 403
    error_message = json.loads(response.get_data())
    assert error_message['message'] == {"token": ["Invalid token: signature, api token is not valid"]}
    current_app.config['ADMIN_CLIENT_SECRET'] = api_secret


def test_authentication_returns_error_when_service_doesnt_exit(
    client,
    sample_api_key
):
    # get service ID and secret the wrong way around
    token = create_jwt_token(
        secret=str(sample_api_key.service_id),
        client_id=str(sample_api_key.id))

    response = client.get(
        '/notifications',
        headers={'Authorization': 'Bearer {}'.format(token)}
    )
    assert response.status_code == 403
    error_message = json.loads(response.get_data())
    assert error_message['message'] == {'token': ['Invalid token: service not found']}


def test_authentication_returns_error_when_service_inactive(client, sample_api_key):
    sample_api_key.service.active = False
    token = create_jwt_token(secret=str(sample_api_key.id), client_id=str(sample_api_key.service_id))

    response = client.get('/notifications', headers={'Authorization': 'Bearer {}'.format(token)})

    assert response.status_code == 403
    error_message = json.loads(response.get_data())
    assert error_message['message'] == {'token': ['Invalid token: service is archived']}


def test_authentication_returns_error_when_service_has_no_secrets(client,
                                                                  sample_service,
                                                                  fake_uuid):
    token = create_jwt_token(
        secret=fake_uuid,
        client_id=str(sample_service.id))

    request.headers = {'Authorization': 'Bearer {}'.format(token)}
    with pytest.raises(AuthError) as exc:
        validate_service_api_key_auth()
    assert exc.value.short_message == 'Invalid token: service has no API keys'
    assert exc.value.service_id == sample_service.id


def test_should_attach_the_current_api_key_to_current_app(notify_api, sample_service, sample_api_key):
    with notify_api.test_request_context(), notify_api.test_client() as client:
        token = __create_token(sample_api_key.service_id)
        response = client.get(
            '/notifications',
            headers={'Authorization': 'Bearer {}'.format(token)}
        )
        assert response.status_code == 200
        assert api_user == sample_api_key


def test_should_return_403_when_token_is_expired(client,
                                                 sample_api_key):
    with freeze_time('2001-01-01T12:00:00'):
        token = __create_token(sample_api_key.service_id)
    with freeze_time('2001-01-01T12:00:40'):
        with pytest.raises(AuthError) as exc:
            request.headers = {'Authorization': 'Bearer {}'.format(token)}
            validate_service_api_key_auth()
    assert exc.value.short_message == 'Error: Your system clock must be accurate to within 30 seconds'
    assert exc.value.service_id == sample_api_key.service_id
    assert exc.value.api_key_id == sample_api_key.id


def __create_token(service_id):
    return create_jwt_token(secret=get_unsigned_secrets(service_id)[0],
                            client_id=str(service_id))


@pytest.mark.parametrize('check_proxy_header,header_value,expected_status', [
    (True, 'key_1', 200),
    (True, 'wrong_key', 200),
    (False, 'key_1', 200),
    (False, 'wrong_key', 200),
])
def test_proxy_key_non_auth_endpoint(notify_api, check_proxy_header, header_value, expected_status):
    with set_config_values(notify_api, {
        'ROUTE_SECRET_KEY_1': 'key_1',
        'ROUTE_SECRET_KEY_2': '',
        'CHECK_PROXY_HEADER': check_proxy_header,
    }):

        with notify_api.test_client() as client:
            response = client.get(
                path='/_status',
                headers=[
                    ('X-Custom-Forwarder', header_value),
                ]
            )
        assert response.status_code == expected_status


@pytest.mark.parametrize('check_proxy_header,header_value,expected_status', [
    (True, 'key_1', 200),
    (True, 'wrong_key', 403),
    (False, 'key_1', 200),
    (False, 'wrong_key', 200),
])
def test_proxy_key_on_admin_auth_endpoint(notify_api, check_proxy_header, header_value, expected_status):
    token = create_jwt_token(current_app.config['ADMIN_CLIENT_SECRET'], current_app.config['ADMIN_CLIENT_USER_NAME'])

    with set_config_values(notify_api, {
        'ROUTE_SECRET_KEY_1': 'key_1',
        'ROUTE_SECRET_KEY_2': '',
        'CHECK_PROXY_HEADER': check_proxy_header,
    }):

        with notify_api.test_client() as client:
            response = client.get(
                path='/service',
                headers=[
                    ('X-Custom-Forwarder', header_value),
                    ('Authorization', 'Bearer {}'.format(token))
                ]
            )
        assert response.status_code == expected_status


class TestRequiresUserInService:

    def test_accepts_jwt_for_user_in_service(self, client, db_session):

        @requires_user_in_service_or_admin()
        def endpoint_that_requires_user_in_service():
            pass

        user = create_user()
        service = create_service(service_name='some-service', user=user)

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_user_in_service()

    def test_rejects_jwt_for_user_not_in_service(self, client, db_session):

        @requires_user_in_service_or_admin()
        def endpoint_that_requires_user_in_service():
            pass

        user = create_user()
        service = create_service(service_name='some-service')

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        with pytest.raises(AuthError) as error:
            endpoint_that_requires_user_in_service()

        assert error.value.code == 403

    def test_401_error_when_bearer_token_expired(self, client, db_session, mocker):

        @requires_user_in_service_or_admin()
        def endpoint_that_requires_user_in_service():
            pass

        user = create_user()
        service = create_service(service_name='some-service')

        token = create_access_token(identity=user)
        mocker.patch("app.authentication.auth.verify_jwt_in_request", side_effect=ExpiredSignatureError)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        with pytest.raises(AuthError) as error:
            endpoint_that_requires_user_in_service()

        assert error.value.code == 401

    @pytest.mark.parametrize('required_permission', PERMISSION_LIST)
    def test_accepts_jwt_with_permission_for_service(self, client, db_session, required_permission):

        @requires_user_in_service_or_admin(required_permission=required_permission)
        def endpoint_that_requires_permission_for_service():
            pass

        user = create_user()
        service = create_service(service_name='some-service')

        dao_add_user_to_service(
            service,
            user,
            permissions=[Permission(service=service, user=user, permission=required_permission)]
        )

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_permission_for_service()

    def test_rejects_jwt_without_permission_for_service(self, client, db_session):

        @requires_user_in_service_or_admin(required_permission='some-required-permission')
        def endpoint_that_requires_permission_for_service():
            pass

        user = create_user()
        service = create_service(service_name='some-service')

        dao_add_user_to_service(service, user, permissions=[])

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        with pytest.raises(AuthError) as error:
            endpoint_that_requires_permission_for_service()

        assert error.value.code == 403

    def test_accepts_jwt_for_platform_admin(self, client, db_session):

        @requires_user_in_service_or_admin()
        def endpoint_that_requires_user_in_service():
            pass

        user = create_user(platform_admin=True)
        service = create_service(service_name='some-service')

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_user_in_service()

    @pytest.mark.parametrize('required_permission', PERMISSION_LIST)
    def test_accepts_jwt_for_platform_admin_even_with_required_permissions(self, client,
                                                                           db_session, required_permission):

        @requires_user_in_service_or_admin(required_permission=required_permission)
        def endpoint_that_requires_permission_for_service():
            pass

        user = create_user(platform_admin=True)
        service = create_service(service_name='some-service')

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_permission_for_service()


class TestRequiresAdminAuthOrUserInService:

    @pytest.mark.parametrize('required_permission', PERMISSION_LIST)
    def test_accepts_jwt_with_permission_for_service(self, client, db_session, required_permission):

        @requires_admin_auth_or_user_in_service(required_permission=required_permission)
        def endpoint_that_requires_admin_auth_or_permission_for_service():
            pass

        user = create_user()
        service = create_service(service_name='some-service')

        dao_add_user_to_service(
            service,
            user,
            permissions=[Permission(service=service, user=user, permission=required_permission)]
        )

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_admin_auth_or_permission_for_service()

    def test_rejects_jwt_without_permission_for_service(self, client, db_session):

        @requires_admin_auth_or_user_in_service(required_permission='some-required-permission')
        def endpoint_that_requires_admin_auth_or_permission_for_service():
            pass

        user = create_user()
        service = create_service(service_name='some-service')

        dao_add_user_to_service(service, user, permissions=[])

        token = create_access_token(identity=user)

        request.view_args['service_id'] = service.id
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        with pytest.raises(AuthError) as error:
            endpoint_that_requires_admin_auth_or_permission_for_service()

        assert error.value.code == 403

    @pytest.mark.parametrize('required_permission', PERMISSION_LIST)
    def test_accepts_admin_jwt(self, client, db_session, required_permission):

        @requires_admin_auth_or_user_in_service(required_permission=required_permission)
        def endpoint_that_requires_admin_auth_or_permission_for_service():
            pass

        token = create_jwt_token(
            current_app.config['ADMIN_CLIENT_SECRET'],
            current_app.config['ADMIN_CLIENT_USER_NAME']
        )

        request.view_args['service_id'] = 'some-service-id'
        request.headers = {'Authorization': 'Bearer {}'.format(token)}

        endpoint_that_requires_admin_auth_or_permission_for_service()
