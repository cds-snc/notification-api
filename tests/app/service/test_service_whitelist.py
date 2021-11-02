import uuid
import json
import pytest
from flask import url_for
from flask_jwt_extended import create_access_token

from tests.app.db import create_user
from tests.app.factories.service_whitelist import a_service_whitelist
from app.models import (
    ServiceWhitelist, Permission, MANAGE_SETTINGS,
    MOBILE_TYPE, EMAIL_TYPE)
from app.dao.services_dao import dao_add_user_to_service
from app.dao.service_whitelist_dao import dao_add_and_commit_whitelisted_contacts


def _create_auth_header(service=None, platform_admin: bool = False):
    if platform_admin:
        user = create_user(email='foo@bar.com', platform_admin=True)
    else:
        user = create_user(email='foo@bar.com')
        dao_add_user_to_service(service, user,
                                permissions=[Permission(service=service, user=user, permission=MANAGE_SETTINGS)])
    token = create_access_token(user)
    return ('Authorization', f'Bearer {token}')


class TestGetServiceWhitelist:

    @pytest.mark.parametrize('platform_admin', [False, True])
    def test_get_whitelist_returns_data(self, db_session, client, sample_service, platform_admin):
        service_whitelist = a_service_whitelist(sample_service.id)
        dao_add_and_commit_whitelisted_contacts([service_whitelist])

        response = client.get(
            url_for('service_whitelist.get_whitelist', service_id=sample_service.id),
            headers=[_create_auth_header(service=sample_service, platform_admin=platform_admin)]
        )
        assert response.status_code == 200
        assert json.loads(response.get_data(as_text=True)) == {
            'email_addresses': [service_whitelist.recipient],
            'phone_numbers': []
        }

    @pytest.mark.parametrize('platform_admin', [False, True])
    def test_get_whitelist_separates_emails_and_phones(self, db_session, client, sample_service, platform_admin):
        dao_add_and_commit_whitelisted_contacts([
            ServiceWhitelist.from_string(sample_service.id, EMAIL_TYPE, 'service@example.com'),
            ServiceWhitelist.from_string(sample_service.id, MOBILE_TYPE, '6502532222'),
            ServiceWhitelist.from_string(sample_service.id, MOBILE_TYPE, '+1800-234-1242'),
        ])

        response = client.get(
            url_for('service_whitelist.get_whitelist', service_id=sample_service.id),
            headers=[_create_auth_header(service=sample_service, platform_admin=platform_admin)])

        assert response.status_code == 200
        json_resp = json.loads(response.get_data(as_text=True))
        assert json_resp['email_addresses'] == ['service@example.com']
        assert sorted(json_resp['phone_numbers']) == sorted(['+1800-234-1242', '6502532222'])

    @pytest.mark.parametrize('platform_admin', [False, True])
    def test_get_whitelist_returns_no_data(self, db_session, client, sample_service, platform_admin):
        response = client.get(
            url_for('service_whitelist.get_whitelist', service_id=sample_service.id),
            headers=[_create_auth_header(service=sample_service, platform_admin=platform_admin)]
        )

        assert response.status_code == 200
        assert json.loads(response.get_data(as_text=True)) == {'email_addresses': [], 'phone_numbers': []}

    # This only applies to platform admins.
    # We require users to have permissions for a given service. No service => no permissions.
    def test_get_whitelist_404s_with_unknown_service_id(self, db_session, client):
        response = client.get(
            url_for('service_whitelist.get_whitelist', service_id=uuid.uuid4()),
            headers=[_create_auth_header(platform_admin=True)]
        )
        assert response.status_code == 404
        json_resp = json.loads(response.get_data(as_text=True))
        assert json_resp['result'] == 'error'
        assert json_resp['message'] == 'No result found'

    def test_should_return_403_if_no_permissions(self, db_session, client, sample_service):
        user = create_user(email='foo@bar.com')
        dao_add_user_to_service(sample_service, user, permissions=[])

        response = client.get(
            url_for('service_whitelist.get_whitelist', service_id=sample_service.id),
            headers=[('Authorization', f'Bearer {create_access_token(user)}')])

        assert response.status_code == 403


class TestUpdateServiceWhitelist:

    @pytest.mark.parametrize('platform_admin', [False, True])
    def test_update_whitelist_replaces_old_whitelist(self, client, sample_service, platform_admin):
        service_whitelist = a_service_whitelist(sample_service.id)
        dao_add_and_commit_whitelisted_contacts([service_whitelist])

        data = {
            'email_addresses': ['foo@bar.com'],
            'phone_numbers': ['6502532222']
        }

        response = client.put(
            url_for('service_whitelist.update_whitelist', service_id=sample_service.id),
            data=json.dumps(data),
            headers=[
                ('Content-Type', 'application/json'),
                _create_auth_header(service=sample_service, platform_admin=platform_admin)
            ]
        )

        assert response.status_code == 204
        whitelist = ServiceWhitelist.query.order_by(ServiceWhitelist.recipient).all()
        assert len(whitelist) == 2
        assert whitelist[0].recipient == '6502532222'
        assert whitelist[1].recipient == 'foo@bar.com'

    def test_update_whitelist_doesnt_remove_old_whitelist_if_error(self, client, sample_service):
        service_whitelist = a_service_whitelist(sample_service.id)
        dao_add_and_commit_whitelisted_contacts([service_whitelist])

        data = {
            'email_addresses': [''],
            'phone_numbers': ['6502532222']
        }

        response = client.put(
            url_for('service_whitelist.update_whitelist', service_id=sample_service.id),
            data=json.dumps(data),
            headers=[
                ('Content-Type', 'application/json'),
                _create_auth_header(service=sample_service)
            ]
        )

        assert response.status_code == 400
        assert json.loads(response.get_data(as_text=True)) == {
            'result': 'error',
            'message': 'Invalid whitelist: "" is not a valid email address or phone number'
        }
        whitelist = ServiceWhitelist.query.one()
        assert whitelist.id == service_whitelist.id

    # This only applies to platform admins.
    # We require users to have permissions for a given service. No service => no permissions.
    def test_should_return_404_if_service_does_not_exist(self, db_session, client):
        data = {
            'email_addresses': [''],
            'phone_numbers': ['6502532222']
        }

        response = client.get(
            url_for('service_whitelist.update_whitelist', service_id=uuid.uuid4()),
            data=json.dumps(data),
            headers=[_create_auth_header(platform_admin=True)]
        )
        assert response.status_code == 404
        json_resp = json.loads(response.get_data(as_text=True))
        assert json_resp['result'] == 'error'
        assert json_resp['message'] == 'No result found'

    def test_should_return_403_if_no_permissions(self, db_session, client, sample_service):
        user = create_user(email='foo@bar.com')
        dao_add_user_to_service(sample_service, user, permissions=[])

        data = {
            'email_addresses': [''],
            'phone_numbers': ['6502532222']
        }

        response = client.put(
            url_for('service_whitelist.update_whitelist', service_id=sample_service.id),
            data=json.dumps(data),
            headers=[
                ('Content-Type', 'application/json'),
                ('Authorization', f'Bearer {create_access_token(user)}')
            ])

        assert response.status_code == 403
