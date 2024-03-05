import json

import pytest

from flask import url_for

from app.dao.permissions_dao import default_service_permissions
from app.model import EMAIL_AUTH_TYPE
from tests import create_admin_authorization_header


def test_get_user_list(admin_request, sample_service):
    """
    Tests GET endpoint '/' to retrieve entire user list.
    """
    service = sample_service()
    json_resp = admin_request.get('user.get_user')

    # it may have the notify user in the DB still :weary:
    assert len(json_resp['data']) >= 1
    sample_user = service.users[0]
    expected_permissions = default_service_permissions
    fetched = next(x for x in json_resp['data'] if x['id'] == str(sample_user.id))

    assert sample_user.name == fetched['name']
    assert sample_user.mobile_number == fetched['mobile_number']
    assert sample_user.email_address == fetched['email_address']
    assert sample_user.state == fetched['state']
    assert sorted(expected_permissions) == sorted(fetched['permissions'][str(service.id)])


def test_get_user(
    admin_request,
    sample_service,
    sample_organisation,
):
    """
    Tests GET endpoint '/<user_id>' to retrieve a single service.
    """
    service = sample_service()
    user = service.users[0]
    org = sample_organisation()
    user.organisations = [org]
    json_resp = admin_request.get('user.get_user', user_id=user.id)

    expected_permissions = default_service_permissions
    fetched = json_resp['data']

    assert fetched['id'] == str(user.id)
    assert fetched['name'] == user.name
    assert fetched['mobile_number'] == user.mobile_number
    assert fetched['email_address'] == user.email_address
    assert fetched['state'] == user.state
    assert fetched['auth_type'] == EMAIL_AUTH_TYPE
    assert fetched['permissions'].keys() == {str(service.id)}
    assert fetched['services'] == [str(service.id)]
    assert fetched['organisations'] == [str(org.id)]
    assert sorted(fetched['permissions'][str(service.id)]) == sorted(expected_permissions)


def test_get_user_doesnt_return_inactive_services_and_orgs(
    admin_request,
    sample_service,
    sample_organisation,
):
    """
    Tests GET endpoint '/<user_id>' to retrieve a single service.
    """
    org = sample_organisation()
    service = sample_service()
    service.active = False
    org.active = False

    sample_user = service.users[0]
    sample_user.organisations = [org]

    json_resp = admin_request.get('user.get_user', user_id=sample_user.id)

    fetched = json_resp['data']

    assert fetched['id'] == str(sample_user.id)
    assert fetched['services'] == []
    assert fetched['organisations'] == []
    assert fetched['permissions'] == {}


@pytest.mark.parametrize('user_perm', default_service_permissions)
def test_get_user_with_permissions(
    client,
    sample_service,
    user_perm,
):
    service = sample_service()
    user = service.users[0]

    # Default permission
    permissions = user.get_permissions(service.id)
    assert user_perm in permissions

    header = create_admin_authorization_header()
    response = client.get(url_for('user.get_user', user_id=str(user.id)), headers=[header])
    assert response.status_code == 200
    permissions = json.loads(response.get_data(as_text=True))['data']['permissions']
    assert user_perm in permissions[str(service.id)]
