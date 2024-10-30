import json

from flask import url_for
from sqlalchemy import delete, select, Table
from uuid import uuid4


from app import db
from app.constants import KEY_TYPE_NORMAL
from app.models import ApiKey
from app.dao.api_key_dao import expire_api_key
from tests import create_admin_authorization_header


def test_api_key_should_create_new_api_key_for_service(notify_api, notify_db_session, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service = sample_service()
            data = {'name': 'some secret name', 'created_by': str(service.created_by.id), 'key_type': KEY_TYPE_NORMAL}
            auth_header = create_admin_authorization_header()
            response = client.post(
                url_for('service.create_api_key', service_id=service.id),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 201
            assert 'data' in json.loads(response.get_data(as_text=True))
            saved_api_key = notify_db_session.session.scalar(select(ApiKey).where(ApiKey.service_id == service.id))
            assert saved_api_key.service_id == service.id
            assert saved_api_key.name == 'some secret name'

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
            api_keys_for_service = notify_db_session.session.get(ApiKey, api_key.id)
            assert api_keys_for_service.expiry_date is not None


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
            stmt = select(ApiKey).where(ApiKey.service_id == service.id)
            query_result = notify_db_session.session.scalars(stmt).all()
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
            stmt = select(ApiKey).where(ApiKey.service_id == service.id)
            query_result = notify_db_session.session.scalars(stmt).all()
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

            # Verify 3 keys are are in the table with the given service id
            stmt = select(ApiKey).where(ApiKey.service_id == service.id)
            assert len(notify_db_session.session.scalars(stmt).all()) == 3

            # Get request verification
            auth_header = create_admin_authorization_header()
            response = client.get(
                url_for('service.get_api_keys', service_id=service.id),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 200
            json_resp = json.loads(response.get_data(as_text=True))
            assert len(json_resp['apiKeys']) == 3

            # DB verification
            stmt = select(ApiKey).where(ApiKey.service_id == service.id)
            assert len(notify_db_session.session.execute(stmt).all()) == 3


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
            stmt = select(ApiKey).where(ApiKey.service_id == service.id)
            assert len(notify_db_session.session.execute(stmt).all()) == 1
