import base64
import json
import pytest
from app.dao.fido2_key_dao import save_fido2_key, create_fido2_session
from app.dao.login_event_dao import save_login_event
from app.dao.permissions_dao import default_service_permissions
from app.dao.service_user_dao import dao_get_service_user, dao_update_service_user
from app.model import User, SMS_AUTH_TYPE, EMAIL_AUTH_TYPE
from app.models import (
    EMAIL_TYPE,
    Fido2Key,
    LoginEvent,
    MANAGE_SETTINGS,
    MANAGE_TEMPLATES,
    Notification,
    Permission,
    SMS_TYPE,
)
from fido2 import cbor
from flask import current_app, url_for
from freezegun import freeze_time
from tests import create_admin_authorization_header
from tests.app.db import create_template_folder, create_organisation, create_reply_to_email
from uuid import UUID, uuid4
from unittest import mock


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


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
# @pytest.mark.xfail(reason="Failing after Flask upgrade.  Not fixed because not used.", run=False)
def test_post_user(client):
    """
    Tests POST endpoint '/' to create a user.
    """

    assert User.query.count() == 0
    data = {
        'name': 'Test User',
        'email_address': 'user@digital.cabinet-office.gov.uk',
        'password': 'tQETOgIO8yzDMyCsDjLZIEVZHAvkFArYfmSI1KTsJnlnPohI2tfIa8kfng7bxCm',
        'mobile_number': '+16502532222',
        'logged_in_at': None,
        'state': 'active',
        'failed_login_count': 0,
        'permissions': {},
        'auth_type': EMAIL_AUTH_TYPE,
    }
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]
    resp = client.post(url_for('user.create_user'), data=json.dumps(data), headers=headers)
    assert resp.status_code == 201
    user = User.query.filter_by(email_address='user@digital.cabinet-office.gov.uk').first()
    json_resp = resp.get_json()
    assert json_resp['data']['email_address'] == user.email_address
    assert json_resp['data']['id'] == str(user.id)
    assert user.auth_type == EMAIL_AUTH_TYPE


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
# @pytest.mark.xfail(reason="Failing after Flask upgrade.  Not fixed because not used.", run=False)
def test_post_user_without_auth_type(admin_request):
    assert User.query.count() == 0
    data = {
        'name': 'Test User',
        'email_address': 'user@digital.cabinet-office.gov.uk',
        'password': 'tQETOgIO8yzDMyCsDjLZIEVZHAvkFArYfmSI1KTsJnlnPohI2tfIa8kfng7bxCm',
        'mobile_number': '+16502532222',
        'permissions': {},
    }

    json_resp = admin_request.post('user.create_user', _data=data, _expected_status=201)

    user = User.query.filter_by(email_address='user@digital.cabinet-office.gov.uk').first()
    assert json_resp['data']['id'] == str(user.id)
    assert user.auth_type == EMAIL_AUTH_TYPE


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_post_user_missing_attribute_email(client):
    """
    Tests POST endpoint '/' missing attribute email.
    """
    assert User.query.count() == 0
    data = {
        'name': 'Test User',
        'password': 'tQETOgIO8yzDMyCsDjLZIEVZHAvkFArYfmSI1KTsJnlnPohI2tfIa8kfng7bxCm',
        'mobile_number': '+16502532222',
        'logged_in_at': None,
        'state': 'active',
        'failed_login_count': 0,
        'permissions': {},
    }
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]
    resp = client.post(url_for('user.create_user'), data=json.dumps(data), headers=headers)
    assert resp.status_code == 400
    assert User.query.count() == 0
    json_resp = resp.get_json()
    assert {'email_address': ['Missing data for required field.']} == json_resp['message']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
# @pytest.mark.xfail(reason="Failing after Flask upgrade.  Not fixed because not used.", run=False)
def test_post_user_with_identity_provider_user_id_without_password(client):
    """
    Tests POST endpoint '/' to create a user with an identity_provider_user_id.
    """
    assert User.query.count() == 0
    data = {
        'name': 'Test User',
        'email_address': 'user@digital.cabinet-office.gov.uk',
        'mobile_number': '+16502532222',
        'logged_in_at': None,
        'state': 'active',
        'failed_login_count': 0,
        'permissions': {},
        'auth_type': EMAIL_AUTH_TYPE,
        'identity_provider_user_id': 'test-id',
    }
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]
    resp = client.post(url_for('user.create_user'), data=json.dumps(data), headers=headers)
    assert resp.status_code == 201
    user = User.query.filter_by(identity_provider_user_id='test-id').first()
    json_resp = resp.get_json()['data']
    assert json_resp['identity_provider_user_id'] == user.identity_provider_user_id
    assert json_resp['email_address'] == user.email_address
    assert json_resp['id'] == str(user.id)
    assert user.auth_type == EMAIL_AUTH_TYPE


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_create_user_missing_attribute_password(client):
    """
    Tests POST endpoint '/' missing attribute password.
    """
    assert User.query.count() == 0
    data = {
        'name': 'Test User',
        'email_address': 'user@digital.cabinet-office.gov.uk',
        'mobile_number': '+16502532222',
        'logged_in_at': None,
        'state': 'active',
        'failed_login_count': 0,
        'permissions': {},
    }
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]
    resp = client.post(url_for('user.create_user'), data=json.dumps(data), headers=headers)
    assert resp.status_code == 400
    assert User.query.count() == 0
    json_resp = resp.get_json()
    assert {'password': ['Missing data for required field.']} == json_resp['message']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_create_user_with_known_bad_password(client):
    """
    Tests POST endpoint '/' missing attribute password.
    """
    assert User.query.count() == 0
    data = {
        'name': 'Test User',
        'password': 'Password',
        'email_address': 'user@digital.cabinet-office.gov.uk',
        'mobile_number': '+16502532222',
        'logged_in_at': None,
        'state': 'active',
        'failed_login_count': 0,
        'permissions': {},
    }
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]
    resp = client.post(url_for('user.create_user'), data=json.dumps(data), headers=headers)
    assert resp.status_code == 400
    assert User.query.count() == 0
    json_resp = resp.get_json()
    assert {'password': ['Password is blacklisted.']} == json_resp['message']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
# @pytest.mark.xfail(reason="Failing after Flask upgrade.  Not fixed because not used.", run=False)
def test_can_create_user_with_email_auth_and_no_mobile(admin_request):
    data = {
        'name': 'Test User',
        'email_address': 'user@digital.cabinet-office.gov.uk',
        'password': 'tQETOgIO8yzDMyCsDjLZIEVZHAvkFArYfmSI1KTsJnlnPohI2tfIa8kfng7bxCm',
        'mobile_number': None,
        'auth_type': EMAIL_AUTH_TYPE,
    }

    json_resp = admin_request.post('user.create_user', _data=data, _expected_status=201)

    assert json_resp['data']['auth_type'] == EMAIL_AUTH_TYPE
    assert json_resp['data']['mobile_number'] is None


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_cannot_create_user_with_sms_auth_and_no_mobile(admin_request):
    data = {
        'name': 'Test User',
        'email_address': 'user@digital.cabinet-office.gov.uk',
        'password': 'tQETOgIO8yzDMyCsDjLZIEVZHAvkFArYfmSI1KTsJnlnPohI2tfIa8kfng7bxCm',
        'mobile_number': None,
        'auth_type': SMS_AUTH_TYPE,
    }

    json_resp = admin_request.post('user.create_user', _data=data, _expected_status=400)

    assert json_resp['message'] == 'Mobile number must be set if auth_type is set to sms_auth'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
# @pytest.mark.xfail(reason="Failing after Flask upgrade.  Not fixed because not used.", run=False)
def test_cannot_create_user_with_empty_strings(admin_request):
    data = {
        'name': '',
        'email_address': '',
        'password': 'tQETOgIO8yzDMyCsDjLZIEVZHAvkFArYfmSI1KTsJnlnPohI2tfIa8kfng7bxCm',
        'mobile_number': '',
        'auth_type': EMAIL_AUTH_TYPE,
    }
    resp = admin_request.post('user.create_user', _data=data, _expected_status=400)
    assert resp['message'] == {
        'email_address': ['Not a valid email address'],
        'mobile_number': ['Invalid phone number: Not a valid number'],
        'name': ['Invalid name'],
    }


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'user_attribute, user_value',
    [
        ('name', 'New User'),
        ('email_address', 'newuser@mail.com'),
        ('mobile_number', '+16502532223'),
        ('identity_provider_user_id', 'test-id'),
    ],
)
def test_post_user_attribute(
    client, mocker, user_attribute, user_value, sample_notify_service_user_session, sample_template_session
):
    service, user = sample_notify_service_user_session()
    sample_template_session(
        service=service,
        user=user,
        name='ACCOUNT_CHANGE_TEMPLATE_ID',
        id=current_app.config['ACCOUNT_CHANGE_TEMPLATE_ID'],
        content='Your account was changed',
        subject='Your account was changed',
        template_type=EMAIL_TYPE,
    )
    # raise
    assert getattr(user, user_attribute) != user_value
    update_dict = {user_attribute: user_value}
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]

    mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')

    with client.application.app_context():
        resp = client.post(
            url_for('user.update_user_attribute', user_id=user.id), data=json.dumps(update_dict), headers=headers
        )

    assert resp.status_code == 200
    json_resp = resp.get_json()
    assert json_resp['data'][user_attribute] == user_value


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'user_attribute, user_value',
    [
        ('name', 'New User'),
        ('email_address', 'newuser@mail.com'),
        ('mobile_number', '+16502532223'),
    ],
)
def test_post_user_attribute_send_notification_email(
    client, mocker, sample_user, user_attribute, user_value, account_change_template
):
    user = sample_user()
    assert getattr(user, user_attribute) != user_value
    update_dict = {user_attribute: user_value}
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]

    mock_persist_notification = mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')

    resp = client.post(
        url_for('user.update_user_attribute', user_id=user.id), data=json.dumps(update_dict), headers=headers
    )

    mock_persist_notification.assert_called()
    assert resp.status_code == 200
    json_resp = resp.get_json()
    assert json_resp['data'][user_attribute] == user_value


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'user_attribute, user_value, arguments',
    [
        ('name', 'New User', None),
        (
            'email_address',
            'newuser@mail.com',
            dict(
                api_key_id=None,
                key_type='normal',
                notification_type=EMAIL_TYPE,
                personalisation={
                    'name': 'Test User',
                    'servicemanagername': 'Service Manago',
                    'change_type': '\n- email address\n',
                    'email address': 'newuser@mail.com',
                },
                recipient='newuser@mail.com',
                reply_to_text='notify@gov.uk',
                service_id=mock.ANY,
                template_id=UUID('c73f1d71-4049-46d5-a647-d013bdeca3f0'),
                template_version=1,
            ),
        ),
        (
            'mobile_number',
            '+16502532223',
            dict(
                api_key_id=None,
                key_type='normal',
                notification_type=SMS_TYPE,
                personalisation={
                    'name': 'Test User',
                    'servicemanagername': 'Service Manago',
                    'change_type': '\n- mobile number\n',
                    'email address': 'notify@digital.cabinet-office.gov.uk',
                },
                recipient='+16502532223',
                reply_to_text='testing',
                service_id=mock.ANY,
                template_id=UUID('8a31520f-4751-4789-8ea1-fe54496725eb'),
                template_version=1,
            ),
        ),
    ],
)
def test_post_user_attribute_with_updated_by(
    client,
    mocker,
    sample_user,
    user_attribute,
    sample_notify_service_user_session,
    sample_template_session,
    user_value,
    arguments,
    team_member_email_edit_template,
    team_member_mobile_edit_template,
):
    service, user = sample_notify_service_user_session()
    # Email template
    sample_template_session(
        service=service,
        user=user,
        name='TEAM_MEMBER_EDIT_EMAIL_TEMPLATE_ID',
        content='Hi ((name)) ((servicemanagername)) changed your email to ((email address))',
        # subject='Your VA Notify email address has changed',
        template_type=EMAIL_TYPE,
    )

    # template_config_name='TEAM_MEMBER_EDIT_EMAIL_TEMPLATE_ID',
    # content='Hi ((name)) ((servicemanagername)) changed your email to ((email address))',
    # subject='Your GOV.UK Notify email address has changed',
    # template_type=EMAIL_TYPE

    # service=service,
    # user=user,
    # template_config_name='TEAM_MEMBER_EDIT_MOBILE_TEMPLATE_ID',
    # content='Your mobile number was changed by ((servicemanagername)).',
    # template_type=SMS_TYPE

    updater = sample_user(name='Service Manago', email='notify_manago@va.gov')
    user = sample_user()
    assert getattr(user, user_attribute) != user_value
    update_dict = {user_attribute: user_value, 'updated_by': str(updater.id)}
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]
    mock_persist_notification = mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')
    resp = client.post(
        url_for('user.update_user_attribute', user_id=user.id), data=json.dumps(update_dict), headers=headers
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    json_resp = resp.get_json()
    assert json_resp['data'][user_attribute] == user_value

    if arguments:
        mock_persist_notification.assert_any_call(**arguments)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_archive_user(mocker, client, sample_user):
    archive_mock = mocker.patch('app.user.rest.dao_archive_user')
    user = sample_user()
    response = client.post(url_for('user.archive_user', user_id=user.id), headers=[create_admin_authorization_header()])

    assert response.status_code == 204
    archive_mock.assert_called_once_with(user)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_archive_user_when_user_does_not_exist_gives_404(mocker, client, fake_uuid):
    archive_mock = mocker.patch('app.user.rest.dao_archive_user')

    response = client.post(
        url_for('user.archive_user', user_id=fake_uuid), headers=[create_admin_authorization_header()]
    )

    assert response.status_code == 404
    archive_mock.assert_not_called()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_archive_user_when_user_cannot_be_archived(mocker, client, sample_user):
    mocker.patch('app.dao.users_dao.user_can_be_archived', return_value=False)

    response = client.post(
        url_for('user.archive_user', user_id=sample_user().id), headers=[create_admin_authorization_header()]
    )
    json_resp = json.loads(response.get_data(as_text=True))

    msg = 'User can’t be removed from a service - check all services have another team member with manage_settings'

    assert response.status_code == 400
    assert json_resp['message'] == msg


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_user_by_email(client, sample_service):
    service = sample_service()
    sample_user = service.users[0]
    header = create_admin_authorization_header()
    url = url_for('user.get_by_email', email=sample_user.email_address)
    resp = client.get(url, headers=[header])
    assert resp.status_code == 200

    json_resp = resp.get_json()
    expected_permissions = default_service_permissions
    fetched = json_resp['data']

    assert str(sample_user.id) == fetched['id']
    assert sample_user.name == fetched['name']
    assert sample_user.mobile_number == fetched['mobile_number']
    assert sample_user.email_address == fetched['email_address']
    assert sample_user.state == fetched['state']
    assert sorted(expected_permissions) == sorted(fetched['permissions'][str(service.id)])


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_user_by_email_not_found_returns_404(client):
    header = create_admin_authorization_header()
    url = url_for('user.get_by_email', email='no_user@digital.gov.uk')
    resp = client.get(url, headers=[header])
    assert resp.status_code == 404
    json_resp = resp.get_json()
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == 'No result found'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_user_by_email_bad_url_returns_404(client):
    header = create_admin_authorization_header()
    url = '/user/email'
    resp = client.get(url, headers=[header])
    assert resp.status_code == 400
    json_resp = resp.get_json()
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == 'Invalid request. Email query string param required'


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


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_set_user_permissions(client, sample_service, sample_user):
    service = sample_service()
    user = sample_user()
    data = json.dumps({'permissions': [{'permission': MANAGE_SETTINGS}]})
    header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), header]
    response = client.post(
        url_for('user.set_permissions', user_id=str(user.id), service_id=str(service.id)),
        headers=headers,
        data=data,
    )

    assert response.status_code == 204
    permission = Permission.query.filter_by(permission=MANAGE_SETTINGS).first()
    assert permission.user == user
    assert permission.service == service
    assert permission.permission == MANAGE_SETTINGS


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_set_user_permissions_multiple(client, sample_service, sample_user):
    service = sample_service()
    user = sample_user()
    data = json.dumps({'permissions': [{'permission': MANAGE_SETTINGS}, {'permission': MANAGE_TEMPLATES}]})
    header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), header]
    response = client.post(
        url_for('user.set_permissions', user_id=str(user.id), service_id=str(service.id)),
        headers=headers,
        data=data,
    )

    assert response.status_code == 204
    permission = Permission.query.filter_by(permission=MANAGE_SETTINGS).first()
    assert permission.user == user
    assert permission.service == service
    assert permission.permission == MANAGE_SETTINGS
    permission = Permission.query.filter_by(permission=MANAGE_TEMPLATES).first()
    assert permission.user == user
    assert permission.service == service
    assert permission.permission == MANAGE_TEMPLATES


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_set_user_permissions_remove_old(client, sample_service, sample_user):
    user = sample_user()
    data = json.dumps({'permissions': [{'permission': MANAGE_SETTINGS}]})
    header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), header]
    response = client.post(
        url_for('user.set_permissions', user_id=str(user.id), service_id=str((sample_service()).id)),
        headers=headers,
        data=data,
    )

    assert response.status_code == 204
    query = Permission.query.filter_by(user=user)
    assert query.count() == 1
    assert query.first().permission == MANAGE_SETTINGS


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_set_user_folder_permissions(client, sample_service, sample_user):
    service = sample_service()
    user = sample_user()
    tf1 = create_template_folder(service)
    tf2 = create_template_folder(service)
    data = json.dumps({'permissions': [], 'folder_permissions': [str(tf1.id), str(tf2.id)]})

    response = client.post(
        url_for('user.set_permissions', user_id=str(user.id), service_id=str(service.id)),
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
        data=data,
    )

    assert response.status_code == 204

    service_user = dao_get_service_user(user.id, sample_service.id)
    assert len(service_user.folders) == 2
    assert tf1 in service_user.folders
    assert tf2 in service_user.folders


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_set_user_folder_permissions_when_user_does_not_belong_to_service(client, sample_service, sample_user):
    service = sample_service()
    tf1 = create_template_folder(service)
    tf2 = create_template_folder(service)

    data = json.dumps({'permissions': [], 'folder_permissions': [str(tf1.id), str(tf2.id)]})

    response = client.post(
        url_for('user.set_permissions', user_id=str(sample_user().id), service_id=str(service.id)),
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
        data=data,
    )

    assert response.status_code == 404


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_set_user_folder_permissions_does_not_affect_permissions_for_other_services(
    client,
    sample_user,
    sample_service,
):
    service = sample_service()
    user = sample_user()
    tf1 = create_template_folder(service)
    tf2 = create_template_folder(service)

    service_2 = sample_service(user, service_name='other service')
    tf3 = create_template_folder(service_2)

    sample_service_user = dao_get_service_user(user.id, service.id)
    sample_service_user.folders = [tf1]
    dao_update_service_user(sample_service_user)

    service_2_user = dao_get_service_user(user.id, service_2.id)
    service_2_user.folders = [tf3]
    dao_update_service_user(service_2_user)

    data = json.dumps({'permissions': [], 'folder_permissions': [str(tf2.id)]})

    response = client.post(
        url_for('user.set_permissions', user_id=str(user.id), service_id=str(service.id)),
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
        data=data,
    )

    assert response.status_code == 204

    assert sample_service_user.folders == [tf2]
    assert service_2_user.folders == [tf3]


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_user_folder_permissions(client, sample_user, sample_service):
    service = sample_service()
    user = sample_user()
    tf1 = create_template_folder(service)
    tf2 = create_template_folder(service)
    tf3 = create_template_folder(service)

    service_user = dao_get_service_user(user.id, service.id)
    service_user.folders = [tf1, tf2]
    dao_update_service_user(service_user)

    data = json.dumps({'permissions': [], 'folder_permissions': [str(tf2.id), str(tf3.id)]})

    response = client.post(
        url_for('user.set_permissions', user_id=str(user.id), service_id=str(service.id)),
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
        data=data,
    )

    assert response.status_code == 204
    assert len(service_user.folders) == 2
    assert tf2 in service_user.folders
    assert tf3 in service_user.folders


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_remove_user_folder_permissions(client, sample_user, sample_service):
    service = sample_service()
    user = sample_user()
    tf1 = create_template_folder(service)
    tf2 = create_template_folder(service)

    service_user = dao_get_service_user(user.id, service.id)
    service_user.folders = [tf1, tf2]
    dao_update_service_user(service_user)

    data = json.dumps({'permissions': [], 'folder_permissions': []})

    response = client.post(
        url_for('user.set_permissions', user_id=str(user.id), service_id=str(sample_service.id)),
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
        data=data,
    )

    assert response.status_code == 204
    assert service_user.folders == []


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@freeze_time('2016-01-01 11:09:00.061258')
def test_send_user_reset_password_should_send_reset_password_link(
    client, sample_user, mocker, password_reset_email_template
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    data = json.dumps({EMAIL_TYPE: sample_user().email_address})
    auth_header = create_admin_authorization_header()
    notify_service = password_reset_email_template.service
    resp = client.post(
        url_for('user.send_user_reset_password'), data=data, headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert resp.status_code == 204
    notification = Notification.query.first()

    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == str(notification.id)

    assert result_queue['queue'] == 'notify-internal-tasks'
    mocked.assert_called_once()

    assert notification.reply_to_text == notify_service.get_default_reply_to_email_address()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_send_user_reset_password_should_return_400_when_email_is_missing(client, mocker):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    data = json.dumps({})
    auth_header = create_admin_authorization_header()

    resp = client.post(
        url_for('user.send_user_reset_password'), data=data, headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert resp.status_code == 400
    assert resp.get_json()['message'] == {EMAIL_TYPE: ['Missing data for required field.']}
    assert mocked.call_count == 0


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_send_user_reset_password_should_return_400_when_user_doesnot_exist(client, mocker):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    bad_email_address = 'bad@email.gov.uk'
    data = json.dumps({EMAIL_TYPE: bad_email_address})
    auth_header = create_admin_authorization_header()

    resp = client.post(
        url_for('user.send_user_reset_password'), data=data, headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert resp.status_code == 404
    assert resp.get_json()['message'] == 'No result found'
    assert mocked.call_count == 0


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_send_user_reset_password_should_return_400_when_data_is_not_email_address(client, mocker):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    bad_email_address = 'bad.email.gov.uk'
    data = json.dumps({EMAIL_TYPE: bad_email_address})
    auth_header = create_admin_authorization_header()

    resp = client.post(
        url_for('user.send_user_reset_password'), data=data, headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert resp.status_code == 400
    assert resp.get_json()['message'] == {EMAIL_TYPE: ['Not a valid email address']}
    assert mocked.call_count == 0


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_send_already_registered_email(client, sample_user, already_registered_template, mocker):
    user = sample_user()
    data = json.dumps({EMAIL_TYPE: user.email_address})
    auth_header = create_admin_authorization_header()
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    notify_service = already_registered_template.service

    resp = client.post(
        url_for('user.send_already_registered_email', user_id=str(user.id)),
        data=data,
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert resp.status_code == 204

    notification = Notification.query.first()
    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == str(notification.id)

    assert result_queue['queue'] == 'notify-internal-tasks'
    mocked.assert_called_once()

    assert notification.reply_to_text == notify_service.get_default_reply_to_email_address()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_send_already_registered_email_returns_400_when_data_is_missing(client, sample_user):
    data = json.dumps({})
    auth_header = create_admin_authorization_header()

    resp = client.post(
        url_for('user.send_already_registered_email', user_id=str(sample_user().id)),
        data=data,
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert resp.status_code == 400
    assert resp.get_json()['message'] == {EMAIL_TYPE: ['Missing data for required field.']}


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
# @pytest.mark.skip(reason="not in use")
def test_send_support_email(client, sample_user, contact_us_template, mocker):
    user = sample_user()
    data = json.dumps({EMAIL_TYPE: user.email_address, 'message': 'test'})
    auth_header = create_admin_authorization_header()
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    notify_service = contact_us_template.service

    resp = client.post(
        url_for('user.send_support_email', user_id=str(user.id)),
        data=data,
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert resp.status_code == 204

    notification = Notification.query.first()
    mocked.assert_called_once_with(([str(notification.id)]), queue='notify-internal-tasks')
    assert notification.reply_to_text == notify_service.get_default_reply_to_email_address()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
# @pytest.mark.skip(reason="not in use")
def test_send_support_email_returns_400_when_data_is_missing(client, sample_user):
    data = json.dumps({})
    auth_header = create_admin_authorization_header()

    resp = client.post(
        url_for('user.send_support_email', user_id=str(sample_user().id)),
        data=data,
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert resp.status_code == 400
    assert resp.get_json()['message'] == {
        EMAIL_TYPE: ['Missing data for required field.'],
        'message': ['Missing data for required field.'],
    }


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_send_user_confirm_new_email_returns_204(client, sample_user, change_email_confirmation_template, mocker):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    new_email = 'new_address@dig.gov.uk'
    data = json.dumps({EMAIL_TYPE: new_email})
    auth_header = create_admin_authorization_header()
    notify_service = change_email_confirmation_template.service

    resp = client.post(
        url_for('user.send_user_confirm_new_email', user_id=str(sample_user().id)),
        data=data,
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert resp.status_code == 204
    notification = Notification.query.first()

    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == str(notification.id)

    assert result_queue['queue'] == 'notify-internal-tasks'
    mocked.assert_called_once()

    assert notification.reply_to_text == notify_service.get_default_reply_to_email_address()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_send_user_confirm_new_email_returns_400_when_email_missing(client, sample_user, mocker):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    data = json.dumps({})
    auth_header = create_admin_authorization_header()
    resp = client.post(
        url_for('user.send_user_confirm_new_email', user_id=str(sample_user().id)),
        data=data,
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert resp.status_code == 400
    assert resp.get_json()['message'] == {EMAIL_TYPE: ['Missing data for required field.']}
    mocked.assert_not_called()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_user_password_saves_correctly(client, sample_service):
    sample_user = sample_service.users[0]
    new_password = 'tQETOgIO8yzDMyCsDjLZIEVZHAvkFArYfmSI1KTsJnlnPohI2tfIa8kfng7bxCm'
    data = {'_password': new_password}
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]
    resp = client.post(url_for('user.update_password', user_id=sample_user.id), data=json.dumps(data), headers=headers)
    assert resp.status_code == 200

    json_resp = resp.get_json()
    assert json_resp['data']['password_changed_at'] is not None
    data = {'password': new_password}
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]
    resp = client.post(
        url_for('user.verify_user_password', user_id=str(sample_user.id)), data=json.dumps(data), headers=headers
    )
    assert resp.status_code == 204


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_user_password_failes_when_banned_password_used(client, sample_service):
    sample_user = sample_service().users[0]
    new_password = 'password'
    data = {'_password': new_password}
    auth_header = create_admin_authorization_header()
    headers = [('Content-Type', 'application/json'), auth_header]
    resp = client.post(url_for('user.update_password', user_id=sample_user.id), data=json.dumps(data), headers=headers)
    assert resp.status_code == 400


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_activate_user(admin_request, sample_user):
    sample_user.state = 'pending'

    resp = admin_request.post('user.activate_user', user_id=sample_user.id)

    assert resp['data']['id'] == str(sample_user.id)
    assert resp['data']['state'] == 'active'
    assert sample_user.state == 'active'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_activate_user_fails_if_already_active(admin_request, sample_user):
    user = sample_user()
    resp = admin_request.post('user.activate_user', user_id=user.id, _expected_status=400)
    assert resp['message'] == 'User already active'
    assert user.state == 'active'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_user_auth_type(admin_request, sample_user, account_change_template, mocker):
    mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')

    user = sample_user()
    assert user.auth_type == 'email_auth'
    resp = admin_request.post(
        'user.update_user_attribute',
        user_id=user.id,
        _data={'auth_type': 'sms_auth'},
    )

    assert resp['data']['id'] == str(user.id)
    assert resp['data']['auth_type'] == 'sms_auth'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_can_set_email_auth_and_remove_mobile_at_same_time(admin_request, sample_user, account_change_template, mocker):
    mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')

    user = sample_user()
    user.auth_type = SMS_AUTH_TYPE

    admin_request.post(
        'user.update_user_attribute',
        user_id=user.id,
        _data={
            'mobile_number': None,
            'auth_type': EMAIL_AUTH_TYPE,
        },
    )

    assert user.mobile_number is None
    assert user.auth_type == EMAIL_AUTH_TYPE


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_cannot_remove_mobile_if_sms_auth(admin_request, sample_user, account_change_template, mocker):
    mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')

    user = sample_user()
    user.auth_type = SMS_AUTH_TYPE

    json_resp = admin_request.post(
        'user.update_user_attribute', user_id=user.id, _data={'mobile_number': None}, _expected_status=400
    )

    assert json_resp['message'] == 'Mobile number must be set if auth_type is set to sms_auth'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_can_remove_mobile_if_email_auth(admin_request, sample_user, account_change_template, mocker):
    mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')

    user = sample_user()
    user.auth_type = EMAIL_AUTH_TYPE

    admin_request.post(
        'user.update_user_attribute',
        user_id=user.id,
        _data={'mobile_number': None},
    )

    assert user.mobile_number is None


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
# @pytest.mark.xfail(reason="Failing after Flask upgrade.  Not fixed because not used.", run=False)
def test_cannot_update_user_with_mobile_number_as_empty_string(
    admin_request, sample_user, account_change_template, mocker
):
    mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')

    user = sample_user()
    user.auth_type = EMAIL_AUTH_TYPE

    resp = admin_request.post(
        'user.update_user_attribute', user_id=user.id, _data={'mobile_number': ''}, _expected_status=400
    )
    assert resp['message']['mobile_number'] == ['Invalid phone number: Not a valid number']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_cannot_update_user_password_using_attributes_method(
    admin_request, sample_user, account_change_template, mocker
):
    mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')
    resp = admin_request.post(
        'user.update_user_attribute', user_id=sample_user().id, _data={'password': 'foo'}, _expected_status=400
    )
    assert resp['message']['_schema'] == ['Unknown field name password']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_can_update_user_attribute_identity_provider_user_id_as_empty(
    admin_request, sample_user, account_change_template, mocker
):
    mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')

    user = sample_user()
    user.auth_type = SMS_AUTH_TYPE
    user.identity_provider_user_id = 'test-id'

    admin_request.post(
        'user.update_user_attribute',
        user_id=user.id,
        _data={
            'identity_provider_user_id': None,
        },
    )

    assert user.identity_provider_user_id is None


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_orgs_and_services_nests_services(admin_request, sample_service, sample_user):
    user = sample_user()
    org1 = create_organisation(name=f'org  {uuid4}')
    org2 = create_organisation(name=f'org {uuid4}')
    service1 = sample_service(service_name=f'service {uuid4}')
    service2 = sample_service(service_name=f'service {uuid4}')
    service3 = sample_service(service_name=f'service {uuid4}')

    org1.services = [service1, service2]
    org2.services = []

    user.organisations = [org1, org2]
    user.services = [service1, service2, service3]

    resp = admin_request.get('user.get_organisations_and_services_for_user', user_id=user.id)

    assert set(resp.keys()) == {
        'organisations',
        'services',
    }
    assert resp['organisations'] == [
        {
            'name': org1.name,
            'id': str(org1.id),
            'count_of_live_services': 2,
        },
        {
            'name': org2.name,
            'id': str(org2.id),
            'count_of_live_services': 0,
        },
    ]
    assert resp['services'] == [
        {
            'name': service1.name,
            'id': str(service1.id),
            'restricted': False,
            'organisation': str(org1.id),
        },
        {
            'name': service2.name,
            'id': str(service2.id),
            'restricted': False,
            'organisation': str(org1.id),
        },
        {
            'name': service3.name,
            'id': str(service3.id),
            'restricted': False,
            'organisation': None,
        },
    ]


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_orgs_and_services_only_returns_active(admin_request, sample_service, sample_user):
    user = sample_user()
    org1 = create_organisation(name=f'org  {uuid4}', active=True)
    org2 = create_organisation(name=f'org  {uuid4}', active=False)

    # in an active org
    service1 = sample_service(service_name=f'service {uuid4}', active=True)
    service2 = sample_service(service_name=f'service {uuid4}', active=False)
    # active but in an inactive org
    service3 = sample_service(service_name=f'service {uuid4}', active=True)
    # not in an org
    service4 = sample_service(service_name=f'service {uuid4}', active=True)
    service5 = sample_service(service_name=f'service {uuid4}', active=False)

    org1.services = [service1, service2]
    org2.services = [service3]

    user.organisations = [org1, org2]
    user.services = [service1, service2, service3, service4, service5]

    resp = admin_request.get('user.get_organisations_and_services_for_user', user_id=user.id)

    assert set(resp.keys()) == {
        'organisations',
        'services',
    }
    assert resp['organisations'] == [
        {
            'name': org1.name,
            'id': str(org1.id),
            'count_of_live_services': 1,
        }
    ]
    assert resp['services'] == [
        {'name': service1.name, 'id': str(service1.id), 'restricted': False, 'organisation': str(org1.id)},
        {'name': service3.name, 'id': str(service3.id), 'restricted': False, 'organisation': str(org2.id)},
        {
            'name': service4.name,
            'id': str(service4.id),
            'restricted': False,
            'organisation': None,
        },
    ]


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_orgs_and_services_only_shows_users_orgs_and_services(admin_request, sample_service, sample_user):
    user = sample_user()
    other_user = sample_user(email=f'{uuid4}other@va.gov')

    org1 = create_organisation(name=f'org {uuid4}')
    org2 = create_organisation(name=f'org {uuid4}')
    service1 = sample_service(service_name=f'service {uuid4}')
    service2 = sample_service(service_name=f'service {uuid4}')

    org1.services = [service1]

    user.organisations = [org2]
    user.services = [service1]

    other_user.organisations = [org1, org2]
    other_user.services = [service1, service2]

    resp = admin_request.get('user.get_organisations_and_services_for_user', user_id=user.id)

    assert set(resp.keys()) == {
        'organisations',
        'services',
    }
    assert resp['organisations'] == [
        {
            'name': org2.name,
            'id': str(org2.id),
            'count_of_live_services': 0,
        }
    ]
    # 'services' always returns the org_id no matter whether the user
    # belongs to that org or not
    assert resp['services'] == [
        {
            'name': service1.name,
            'id': str(service1.id),
            'restricted': False,
            'organisation': str(org1.id),
        }
    ]


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_find_users_by_email_finds_user_by_partial_email(client, sample_user):
    user1 = sample_user(email=f'findel.mestro{uuid4}@foo.com')
    # Insert a few so there's more in the table
    for _ in range(10):
        sample_user(email=f'me.ignorra{uuid4}@foo.com')

    data = json.dumps({EMAIL_TYPE: 'findel'})
    auth_header = create_admin_authorization_header()

    response = client.post(
        url_for('user.find_users_by_email'), data=data, headers=[('Content-Type', 'application/json'), auth_header]
    )
    users = json.loads(response.get_data(as_text=True))

    assert response.status_code == 200
    assert len(users['data']) == 1
    assert users['data'][0]['email_address'] == user1.email_address


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_find_users_by_email_finds_user_by_full_email(client, sample_user):
    user1 = sample_user(email=f'findel.mestro{uuid4}@foo.com')
    # Insert a few so there's more in the table
    for _ in range(10):
        sample_user(email=f'me.ignorra{uuid4}@foo.com')

    data = json.dumps({EMAIL_TYPE: user1.email_address})
    auth_header = create_admin_authorization_header()

    response = client.post(
        url_for('user.find_users_by_email'), data=data, headers=[('Content-Type', 'application/json'), auth_header]
    )
    users = json.loads(response.get_data(as_text=True))

    assert response.status_code == 200
    assert len(users['data']) == 1
    assert users['data'][0]['email_address'] == user1.email_address


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_find_users_by_email_handles_no_results(client, sample_user):
    sample_user(email=f'findel.mestro{uuid4}@foo.com')
    # Insert a few so there's more in the table
    for _ in range(10):
        sample_user(email=f'me.ignorra{uuid4}@foo.com')

    data = json.dumps({EMAIL_TYPE: 'rogue'})
    auth_header = create_admin_authorization_header()

    response = client.post(
        url_for('user.find_users_by_email'), data=data, headers=[('Content-Type', 'application/json'), auth_header]
    )
    users = json.loads(response.get_data(as_text=True))

    assert response.status_code == 200
    assert users['data'] == []


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_search_for_users_by_email_handles_incorrect_data_format(client, sample_user):
    sample_user(email=f'findel.mestro{uuid4}@foo.com')
    data = json.dumps({EMAIL_TYPE: 1})
    auth_header = create_admin_authorization_header()

    response = client.post(
        url_for('user.find_users_by_email'), data=data, headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert response.status_code == 400
    assert json.loads(response.get_data(as_text=True))['message'] == {EMAIL_TYPE: ['Not a valid string.']}


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_list_fido2_keys_for_a_user(client, sample_service):
    sample_user = sample_service().users[0]
    auth_header = create_admin_authorization_header()

    key_one = Fido2Key(name='sample key one', key='abcd', user_id=sample_user.id)
    save_fido2_key(key_one)

    key_two = Fido2Key(name='sample key two', key='abcd', user_id=sample_user.id)
    save_fido2_key(key_two)

    response = client.get(
        url_for('user.list_fido2_keys_user', user_id=sample_user.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 200
    assert list(map(lambda o: o['id'], json.loads(response.get_data(as_text=True)))) == [
        str(key_one.id),
        str(key_two.id),
    ]


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_create_fido2_keys_for_a_user(client, sample_service, mocker, account_change_template):
    service = sample_service()
    sample_user = service.users[0]
    create_reply_to_email(service, 'reply-here@example.canada.ca')
    auth_header = create_admin_authorization_header()

    create_fido2_session(sample_user.id, 'ABCD')

    data = {'name': 'sample key one', 'key': 'abcd'}
    data = cbor.encode(data)
    data = {'payload': base64.b64encode(data).decode('utf-8')}

    mocker.patch('app.user.rest.decode_and_register', return_value='abcd')
    mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')

    response = client.post(
        url_for('user.create_fido2_keys_user', user_id=sample_user.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True))['id']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_delete_fido2_keys_for_a_user(client, sample_service, mocker, account_change_template):
    service = sample_service()
    mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')
    sample_user = service.users[0]
    create_reply_to_email(service, 'reply-here@example.canada.ca')
    auth_header = create_admin_authorization_header()

    key = Fido2Key(name='sample key one', key='abcd', user_id=sample_user.id)
    save_fido2_key(key)

    response = client.get(
        url_for('user.list_fido2_keys_user', user_id=sample_user.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 200
    data = json.loads(response.get_data(as_text=True))

    response = client.delete(
        url_for('user.delete_fido2_keys_user', user_id=sample_user.id, key_id=data[0]['id']),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert Fido2Key.query.count() == 0
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True))['id'] == data[0]['id']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
# @pytest.mark.xfail(reason="Failing after Flask upgrade.  Not fixed because not used.", run=False)
def test_start_fido2_registration(client, sample_service):
    sample_user = sample_service().users[0]
    auth_header = create_admin_authorization_header()

    response = client.post(
        url_for('user.fido2_keys_user_register', user_id=sample_user.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert response.status_code == 200
    data = json.loads(response.get_data())
    data = base64.b64decode(data['data'])
    data = cbor.decode(data)
    assert data['publicKey']['rp']['id'] == 'localhost'
    assert data['publicKey']['user']['id'] == sample_user.id.bytes


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
# @pytest.mark.xfail(reason="Failing after Flask upgrade.  Not fixed because not used.", run=False)
def test_start_fido2_authentication(client, sample_service):
    sample_user = sample_service().users[0]
    auth_header = create_admin_authorization_header()

    response = client.post(
        url_for('user.fido2_keys_user_authenticate', user_id=sample_user.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert response.status_code == 200
    data = json.loads(response.get_data())
    data = base64.b64decode(data['data'])
    data = cbor.decode(data)
    assert data['publicKey']['rpId'] == 'localhost'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_list_login_events_for_a_user(client, sample_service):
    sample_user = sample_service().users[0]
    auth_header = create_admin_authorization_header()

    event_one = LoginEvent(**{'user': sample_user, 'data': {}})
    save_login_event(event_one)

    event_two = LoginEvent(**{'user': sample_user, 'data': {}})
    save_login_event(event_two)

    response = client.get(
        url_for('user.list_login_events_user', user_id=sample_user.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 200
    assert list(map(lambda o: o['id'], json.loads(response.get_data(as_text=True)))) == [
        str(event_two.id),
        str(event_one.id),
    ]


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_user_blocked(admin_request, sample_user, account_change_template, mocker):
    mocker.patch('app.user.rest.persist_notification')
    mocker.patch('app.user.rest.send_notification_to_queue')

    user = sample_user()

    resp = admin_request.post(
        'user.update_user_attribute',
        user_id=user.id,
        _data={'blocked': True},
    )

    assert resp['data']['id'] == str(user.id)
    assert resp['data']['blocked']
