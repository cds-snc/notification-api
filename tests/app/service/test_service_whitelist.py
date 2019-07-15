import uuid
import json

from tests import create_authorization_header

from app.models import (
    ServiceWhitelist,
    MOBILE_TYPE, EMAIL_TYPE)

from app.dao.service_whitelist_dao import dao_add_and_commit_whitelisted_contacts


def test_get_whitelist_returns_data(client, sample_service_whitelist):
    service_id = sample_service_whitelist.service_id

    response = client.get('service/{}/whitelist'.format(service_id), headers=[create_authorization_header()])
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True)) == {
        'email_addresses': [sample_service_whitelist.recipient],
        'phone_numbers': []
    }


def test_get_whitelist_separates_emails_and_phones(client, sample_service):
    dao_add_and_commit_whitelisted_contacts([
        ServiceWhitelist.from_string(sample_service.id, EMAIL_TYPE, 'service@example.com'),
        ServiceWhitelist.from_string(sample_service.id, MOBILE_TYPE, '6502532222'),
        ServiceWhitelist.from_string(sample_service.id, MOBILE_TYPE, '+1800-234-1242'),
    ])

    response = client.get('service/{}/whitelist'.format(sample_service.id), headers=[create_authorization_header()])
    assert response.status_code == 200
    json_resp = json.loads(response.get_data(as_text=True))
    assert json_resp['email_addresses'] == ['service@example.com']
    assert sorted(json_resp['phone_numbers']) == sorted(['+1800-234-1242', '6502532222'])


def test_get_whitelist_404s_with_unknown_service_id(client):
    path = 'service/{}/whitelist'.format(uuid.uuid4())

    response = client.get(path, headers=[create_authorization_header()])
    assert response.status_code == 404
    json_resp = json.loads(response.get_data(as_text=True))
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == 'No result found'


def test_get_whitelist_returns_no_data(client, sample_service):
    path = 'service/{}/whitelist'.format(sample_service.id)

    response = client.get(path, headers=[create_authorization_header()])

    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True)) == {'email_addresses': [], 'phone_numbers': []}


def test_update_whitelist_replaces_old_whitelist(client, sample_service_whitelist):
    data = {
        'email_addresses': ['foo@bar.com'],
        'phone_numbers': ['6502532222']
    }

    response = client.put(
        'service/{}/whitelist'.format(sample_service_whitelist.service_id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), create_authorization_header()]
    )

    assert response.status_code == 204
    whitelist = ServiceWhitelist.query.order_by(ServiceWhitelist.recipient).all()
    assert len(whitelist) == 2
    assert whitelist[0].recipient == '6502532222'
    assert whitelist[1].recipient == 'foo@bar.com'


def test_update_whitelist_doesnt_remove_old_whitelist_if_error(client, sample_service_whitelist):

    data = {
        'email_addresses': [''],
        'phone_numbers': ['6502532222']
    }

    response = client.put(
        'service/{}/whitelist'.format(sample_service_whitelist.service_id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), create_authorization_header()]
    )

    assert response.status_code == 400
    assert json.loads(response.get_data(as_text=True)) == {
        'result': 'error',
        'message': 'Invalid whitelist: "" is not a valid email address or phone number'
    }
    whitelist = ServiceWhitelist.query.one()
    assert whitelist.id == sample_service_whitelist.id
