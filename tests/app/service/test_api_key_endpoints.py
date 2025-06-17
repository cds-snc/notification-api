import json
import uuid
from uuid import uuid4

import pytest
from flask import url_for
from freezegun import freeze_time
from sqlalchemy import delete, select, Table

from app import db
from app.constants import KEY_TYPE_NORMAL, SECRET_TYPE_DEFAULT, SECRET_TYPE_UUID
from app.models import ApiKey
from app.dao.api_key_dao import expire_api_key, get_model_api_keys
from tests import create_admin_authorization_header


def test_api_key_should_create_new_api_key_for_service(notify_api, notify_db_session, sample_service):
    """Test new API key is created with expected data."""
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service = sample_service()
            data = {
                'name': 'some secret name',
                'created_by': str(service.created_by.id),
                'key_type': KEY_TYPE_NORMAL,
            }
            auth_header = create_admin_authorization_header()
            response = client.post(
                url_for('service.create_api_key', service_id=service.id),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 201
            assert 'data' in json.loads(response.get_data(as_text=True))

            saved_api_keys: ApiKey = get_model_api_keys(service.id)
            assert len(saved_api_keys) == 1

            saved_api_key = saved_api_keys[0]
            assert saved_api_key.service_id == service.id
            assert saved_api_key.name == 'some secret name'
            assert saved_api_key.expiry_date is not None

            # Teardown
            # No model for api_keys_history
            ApiKeyHistory = Table('api_keys_history', ApiKey.get_history_model().metadata, autoload_with=db.engine)
            notify_db_session.session.execute(delete(ApiKeyHistory).where(ApiKeyHistory.c.id == saved_api_key.id))
            notify_db_session.session.delete(saved_api_key)
            notify_db_session.session.commit()


def test_api_key_should_return_error_when_service_does_not_exist(notify_api):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            missing_service_id = uuid4()
            auth_header = create_admin_authorization_header()
            response = client.post(
                url_for('service.create_api_key', service_id=missing_service_id),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 404


def test_api_key_should_return_error_when_user_does_not_exist(notify_api, sample_service):
    service = sample_service()

    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            missing_user_id = str(uuid4())
            data = {
                'name': 'some secret name',
                'created_by': missing_user_id,
                'key_type': KEY_TYPE_NORMAL,
            }
            auth_header = create_admin_authorization_header()
            response = client.post(
                url_for('service.create_api_key', service_id=service.id),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 400
            assert 'IntegrityError' in response.json['message']


def test_api_key_should_return_error_when_key_type_invlid(
    notify_api,
    sample_service,
):
    service = sample_service()

    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                'name': 'some secret name',
                'created_by': str(service.created_by.id),
                'key_type': 'fake_type',
            }
            auth_header = create_admin_authorization_header()
            response = client.post(
                url_for('service.create_api_key', service_id=service.id),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 400
            assert 'IntegrityError' in response.json['message']


def test_create_api_key_without_key_type_rejects(notify_api, notify_db_session, sample_service):
    with notify_api.test_request_context(), notify_api.test_client() as client:
        service = sample_service()
        data = {'name': 'some secret name', 'created_by': str(service.created_by.id)}
        auth_header = create_admin_authorization_header()
        response = client.post(
            url_for('service.create_api_key', service_id=service.id),
            data=json.dumps(data),
            headers=[('Content-Type', 'application/json'), auth_header],
        )
        assert response.status_code == 400
        json_resp = json.loads(response.get_data(as_text=True))
        assert json_resp['result'] == 'error'
        assert json_resp['message'] == {'key_type': ['Missing data for required field.']}


def test_revoke_should_expire_api_key_for_service(notify_api, notify_db_session, sample_api_key):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            api_key = sample_api_key()
            api_keys = notify_db_session.session.scalars(
                select(ApiKey).where(ApiKey.service_id == api_key.service_id)
            ).all()

            assert len(api_keys) == 1
            auth_header = create_admin_authorization_header()
            response = client.post(
                url_for('service.revoke_api_key', service_id=api_key.service_id, api_key_id=api_key.id),
                headers=[auth_header],
            )

            # "Accepted" status code
            assert response.status_code == 202
            assert response.get_json() is None
            revoked_api_key: ApiKey = notify_db_session.session.get(ApiKey, api_key.id)
            assert revoked_api_key.expiry_date is not None
            assert revoked_api_key.revoked


def test_api_key_should_create_multiple_new_api_key_for_service(notify_api, notify_db_session, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            api_keys = []
            # Create a service (also generates a user)
            service = sample_service(service_name=f'multiple key test {uuid4()}')
            assert (
                notify_db_session.session.execute(select(ApiKey).where(ApiKey.service_id == service.id)).first() is None
            )

            # Prepare data to create an API key
            data = {
                'name': f'some secret name {uuid4()}',
                'created_by': str(service.created_by_id),
                'key_type': KEY_TYPE_NORMAL,
            }
            auth_header = create_admin_authorization_header()
            response = client.post(
                url_for('service.create_api_key', service_id=service.id),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 201
            query_result = get_model_api_keys(service.id)
            api_keys += query_result
            assert len(query_result) == 1

            # Second key creation
            data['name'] = f'another secret name {uuid4()}'
            auth_header = create_admin_authorization_header()
            response2 = client.post(
                url_for('service.create_api_key', service_id=service.id),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response2.status_code == 201
            assert json.loads(response.get_data(as_text=True)) != json.loads(response2.get_data(as_text=True))
            query_result = get_model_api_keys(service.id)
            api_keys += query_result
            assert len(query_result) == 2

            # Teardown
            # No model for api_keys_history
            ApiKeyHistory = Table('api_keys_history', ApiKey.get_history_model().metadata, autoload_with=db.engine)
            for api_key in api_keys:
                notify_db_session.session.execute(delete(ApiKeyHistory).where(ApiKeyHistory.c.id == api_key.id))
                notify_db_session.session.delete(api_key)
            notify_db_session.session.commit()


def test_get_api_keys_should_return_all_keys_for_service(
    notify_api,
    notify_db_session,
    sample_api_key,
    sample_service,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            bogus_service = sample_service(service_name=f'bogus service {uuid4()}')
            # Bogus key to put data into the DB
            sample_api_key(service=bogus_service)

            service = sample_service(service_name=f'api-key test service {uuid4()}')
            # key for service
            sample_api_key(service=service)

            # this service already has one key, add two more, one expired
            sample_api_key(service=service)
            one_to_expire = sample_api_key(service=service)
            expire_api_key(service_id=one_to_expire.service_id, api_key_id=one_to_expire.id)

            # Second bogus key to put data into the DB after adding to the correct service
            sample_api_key(service=bogus_service)

            # Verify 2 keys are in the table with the given service id
            assert len(get_model_api_keys(service.id)) == 2

            # Get request verification
            auth_header = create_admin_authorization_header()
            response = client.get(
                url_for('service.get_api_keys', service_id=service.id),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 200
            json_resp = json.loads(response.get_data(as_text=True))
            assert len(json_resp['apiKeys']) == 2


def test_get_api_keys_should_return_one_key_for_service(notify_api, notify_db_session, sample_api_key, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service = sample_service()
            api_key = sample_api_key(service=service)
            auth_header = create_admin_authorization_header()

            # Get request verification
            response = client.get(
                url_for('service.get_api_keys', service_id=service.id, key_id=api_key.id),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 200
            json_resp = json.loads(response.get_data(as_text=True))
            assert len(json_resp['apiKeys']) == 1

            # DB verification
            assert len(get_model_api_keys(service.id)) == 1


@pytest.mark.parametrize(
    'include_revoked,num_keys',
    [
        (None, 2),
        (False, 2),
        (True, 3),
        ('True', 3),
        ('T', 3),
        ('true', 3),
        ('t', 3),
    ],
    ids=[
        'include_revoked_none',
        'include_revoked_false_bool',
        'include_revoked_true_bool',
        'include_revoked_true_cap_str',
        'include_revoked_true_cap_char',
        'include_revoked_true_str',
        'include_revoked_true_char',
    ],
)
def test_get_api_keys_with_is_revoked(
    notify_api, notify_db_session, sample_service, sample_api_key, include_revoked, num_keys
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service = sample_service()
            sample_api_key(service=service, key_name='key1')
            sample_api_key(service=service, key_name='key2')
            expired_key = sample_api_key(service=service, key_name='expired_key')
            expire_api_key(service_id=expired_key.service_id, api_key_id=expired_key.id)

            auth_header = create_admin_authorization_header()
            url = url_for('service.get_api_keys', service_id=service.id, include_revoked=include_revoked)
            response = client.get(
                url,
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 200
            json_resp = json.loads(response.get_data(as_text=True))
            assert len(json_resp['apiKeys']) == num_keys


def test_get_api_keys_with_invalid_is_revoked_param(notify_api, notify_db_session, sample_service, sample_api_key):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service = sample_service()
            sample_api_key(service=service, key_name='key1')
            sample_api_key(service=service, key_name='key2')
            expired_key = sample_api_key(service=service, key_name='expired_key')
            expire_api_key(service_id=expired_key.service_id, api_key_id=expired_key.id)

            auth_header = create_admin_authorization_header()
            url = url_for('service.get_api_keys', service_id=service.id, include_revoked='invalid')
            response = client.get(
                url,
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 400
            json_resp = json.loads(response.get_data(as_text=True))
            assert json_resp['message'] == 'Invalid value for include_revoked'


def test_create_api_key_with_uuid_secret_type_returns_201(client, notify_db_session, sample_service):
    """Test end-to-end happy path for requesting UUID-style secret generation through the REST API."""
    service = sample_service()
    data = {
        'secret_type': SECRET_TYPE_UUID,
        'name': 'Integration Test Key',
        'created_by': str(service.created_by.id),
        'key_type': KEY_TYPE_NORMAL,
    }
    auth_header = create_admin_authorization_header()
    response = client.post(
        url_for('service.create_api_key', service_id=service.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 201
    json_resp = json.loads(response.get_data(as_text=True))
    assert 'data' in json_resp

    # Verify the returned secret is a valid UUID format
    try:
        generated_uuid = uuid.UUID(json_resp['data'])
        assert str(generated_uuid) == json_resp['data']
        assert len(json_resp['data']) == 36  # Standard UUID string length
    except ValueError:
        pytest.fail(f'Expected UUID format but got: {json_resp["data"]}')


def test_create_api_key_with_invalid_secret_type_returns_400(client, sample_service):
    """Test proper error handling when invalid secret type values are submitted via the API."""
    service = sample_service()
    data = {
        'secret_type': 'invalid_type',
        'name': 'Test Key',
        'created_by': str(service.created_by.id),
        'key_type': KEY_TYPE_NORMAL,
    }
    auth_header = create_admin_authorization_header()
    response = client.post(
        url_for('service.create_api_key', service_id=service.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    # This should fail until we implement the feature
    assert response.status_code == 400
    json_resp = json.loads(response.get_data(as_text=True))
    assert json_resp['result'] == 'error'
    assert 'Invalid secret type' in json_resp['message'] or 'secret_type' in str(json_resp['message'])


def test_create_api_key_without_secret_type_maintains_backward_compatibility(client, notify_db_session, sample_service):
    """Test that existing API behavior remains unchanged for current consumers."""
    service = sample_service()
    data = {
        'name': 'Backward Compatible Test Key',
        'created_by': str(service.created_by.id),
        'key_type': KEY_TYPE_NORMAL,
    }
    auth_header = create_admin_authorization_header()
    response = client.post(
        url_for('service.create_api_key', service_id=service.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 201
    json_resp = json.loads(response.get_data(as_text=True))
    assert 'data' in json_resp

    # Verify secret is auto-generated using current random token method
    secret = json_resp['data']
    assert secret is not None
    assert len(secret) >= 86  # Current default generates ~86+ chars

    # Verify it's not a UUID format
    with pytest.raises(ValueError):
        uuid.UUID(secret)


def test_create_api_key_with_default_secret_type_returns_201(client, notify_db_session, sample_service):
    """Test end-to-end happy path for requesting default-style secret generation through the REST API."""
    service = sample_service()
    data = {
        'secret_type': SECRET_TYPE_DEFAULT,
        'name': 'Default Test Key',
        'created_by': str(service.created_by.id),
        'key_type': KEY_TYPE_NORMAL,
    }
    auth_header = create_admin_authorization_header()
    response = client.post(
        url_for('service.create_api_key', service_id=service.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 201
    json_resp = json.loads(response.get_data(as_text=True))
    assert 'data' in json_resp

    # Verify the returned secret is in default format (not UUID)
    secret = json_resp['data']
    assert secret is not None
    assert len(secret) >= 86  # Default token_urlsafe(64) generates ~86+ chars

    # Verify it's not a UUID format
    with pytest.raises(ValueError):
        uuid.UUID(secret)


@freeze_time('2025-01-01T11:00:00+00:00')
class TestApiKeyUpdates:
    """Tests for updating API keys, including expiry and revocation."""

    update_key_url = 'service.update_api_key_expiry_date'

    @pytest.mark.parametrize('with_expiry', [True, False])
    def test_update_api_key_expiry_happy_path(self, notify_api, notify_db_session, sample_api_key, with_expiry) -> None:
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                # test with and without expiry_date
                api_key = sample_api_key(with_expiry=with_expiry)

                payload = {'expiry_date': '2025-01-02'}
                auth_header = create_admin_authorization_header()

                response = client.post(
                    url_for(self.update_key_url, service_id=api_key.service_id, api_key_id=api_key.id),
                    data=json.dumps(payload),
                    headers=[('Content-Type', 'application/json'), auth_header],
                )

                assert response.status_code == 200
                notify_db_session.session.refresh(api_key)
                assert api_key.expiry_date.strftime('%Y-%m-%d') == payload['expiry_date']

    @pytest.mark.parametrize(
        'expiry_date',
        [
            '2025-01-01',  # Same day
            '2024-12-31',  # Past date
        ],
        ids=[
            'same_day',
            'past_date',
        ],
    )
    def test_update_api_key_expiry_invalid_date(
        self,
        notify_api,
        notify_db_session,
        sample_api_key,
        expiry_date,
    ) -> None:
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                api_key = sample_api_key()
                payload = {'expiry_date': expiry_date}
                auth_header = create_admin_authorization_header()

                response = client.post(
                    url_for(self.update_key_url, service_id=api_key.service_id, api_key_id=api_key.id),
                    data=json.dumps(payload),
                    headers=[('Content-Type', 'application/json'), auth_header],
                )

                assert response.status_code == 400
                json_resp = json.loads(response.get_data(as_text=True))
                assert 'error' in json_resp['result']
                assert 'Updated expiry_date cannot be in the past' in json_resp['message']

    def test_update_api_key_expiry_invalid_date_str(self, notify_api, notify_db_session, sample_api_key) -> None:
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                api_key = sample_api_key()
                payload = {'expiry_date': 'not-a-date'}
                auth_header = create_admin_authorization_header()

                response = client.post(
                    url_for(self.update_key_url, service_id=api_key.service_id, api_key_id=api_key.id),
                    data=json.dumps(payload),
                    headers=[('Content-Type', 'application/json'), auth_header],
                )

                assert response.status_code == 400
                json_resp = json.loads(response.get_data(as_text=True))
                assert 'ValidationError' in json_resp['errors'][0]['error']

    def test_update_api_key_expiry_not_found(self, notify_api, notify_db_session) -> None:
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                service_id = uuid4()
                api_key_id = uuid4()
                payload = {'expiry_date': '2025-12-31'}
                auth_header = create_admin_authorization_header()

                response = client.post(
                    url_for(self.update_key_url, service_id=service_id, api_key_id=api_key_id),
                    data=json.dumps(payload),
                    headers=[('Content-Type', 'application/json'), auth_header],
                )

                assert response.status_code == 404
