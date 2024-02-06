import json
import pytest
import uuid
from app.dao.organisation_dao import dao_add_service_to_organisation
from app.dao.service_user_dao import dao_get_service_user
from app.dao.services_dao import (
    dao_add_user_to_service,
    dao_remove_user_from_service,
    DEFAULT_SERVICE_PERMISSIONS,
)
from app.dao.templates_dao import dao_redact_template
from app.dao.users_dao import save_model_user
from app.model import User
from app.models import (
    EmailBranding,
    Notification,
    Permission,
    Service,
    ServiceEmailReplyTo,
    ServicePermission,
    ServiceSmsSender,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    EMAIL_TYPE,
    SMS_TYPE,
    LETTER_TYPE,
    INTERNATIONAL_SMS_TYPE,
    INBOUND_SMS_TYPE,
    ProviderDetails,
)
from datetime import datetime, timedelta, date
from flask import url_for, current_app
from freezegun import freeze_time
from sqlalchemy import select
from tests import create_admin_authorization_header
from tests.app.db import (
    create_ft_billing,
    create_ft_notification_status,
    create_template_folder,
    create_notification,
    create_reply_to_email,
    create_organisation,
    create_annual_billing,
)
from unittest.mock import ANY
from uuid import uuid4


def test_get_service_list(client, sample_service, sample_user):
    # Circumvent race conditions by specifying a user with random uuid4
    user = sample_user()
    s1 = sample_service(user=user)
    s2 = sample_service(user=user)
    s3 = sample_service(user=user)
    auth_header = create_admin_authorization_header()
    response = client.get('/service', headers=[auth_header])
    assert response.status_code == 200
    json_resp = response.get_json()

    # user filter
    resp_data = [x['name'] for x in json_resp['data'] if x['created_by'] == str(user.id)]

    assert len(resp_data) == 3
    assert resp_data[0] == s1.name
    assert resp_data[1] == s2.name
    assert resp_data[2] == s3.name


def test_get_service_list_with_only_active_flag(client, sample_service, sample_user):
    # Circumvent race conditions by specifying a user with random uuid4
    user_0 = sample_user()
    user_1 = sample_user()

    # One inactive, two active
    sample_service(user=user_0, active=False)
    active_0 = sample_service(user=user_0)
    active_1 = sample_service(user=user_1)

    auth_header = create_admin_authorization_header()
    response = client.get('/service?only_active=True', headers=[auth_header])
    assert response.status_code == 200
    json_resp = response.get_json()

    # user filter
    users = [str(user_0.id), str(user_1.id)]
    resp_data = [x['name'] for x in json_resp['data'] if x['created_by'] in users]

    assert len(resp_data) == 2
    assert resp_data[0] == str(active_0.name)
    assert resp_data[1] == str(active_1.name)


def test_get_service_list_with_user_id_and_only_active_flag(admin_request, sample_service, sample_user):
    user_0 = sample_user()
    user_1 = sample_user()

    # One inactive, three active
    sample_service(user=user_0, active=False)
    sample_service(user=user_0)
    active_1 = sample_service(user=user_1)
    active_2 = sample_service(user=user_1)

    # Chose user_1
    json_resp = admin_request.get('service.get_services', user_id=user_1.id, only_active=True)

    # user filter
    resp_data = [x['name'] for x in json_resp['data'] if x['created_by'] == str(user_1.id)]

    assert len(resp_data) == 2
    assert resp_data[0] == str(active_1.name)
    assert resp_data[1] == str(active_2.name)


def test_get_service_list_by_user(admin_request, sample_service, sample_user):
    # Circumvent race conditions by specifying a user with random uuid4
    user_0 = sample_user()
    user_1 = sample_user()

    # One inactive, three active
    inactive = sample_service(user=user_0, active=False)
    active_0 = sample_service(user=user_0)
    sample_service(user=user_1)
    sample_service(user=user_1)

    json_resp = admin_request.get('service.get_services', user_id=user_0.id)

    # user filter
    resp_data = [x['name'] for x in json_resp['data'] if x['created_by'] == str(user_0.id)]

    assert len(resp_data) == 2
    assert resp_data[0] == inactive.name
    assert resp_data[1] == active_0.name


def test_get_service_list_by_user_should_return_empty_list_if_no_services(admin_request, sample_service, sample_user):
    # Populate at least one service so it has a chance to fail
    sample_service()

    json_resp = admin_request.get('service.get_services', user_id=sample_user().id)
    assert len(json_resp['data']) == 0


@pytest.mark.serial  # Cannot handle multiple workers
def test_get_service_list_should_return_empty_list_if_no_services(admin_request):
    # Tests involving a check on all services cannot be done with multiple workers
    json_resp = admin_request.get('service.get_services')
    assert len(json_resp['data']) == 0


def test_find_services_by_name_finds_services(admin_request, mocker, sample_service):
    service_0 = sample_service(service_name=f'ABC {uuid4()}')
    service_1 = sample_service(service_name=f'ABC {uuid4()}')

    mock_get_services_by_partial_name = mocker.patch(
        'app.service.rest.get_services_by_partial_name', return_value=[service_0, service_1]
    )
    response = admin_request.get('service.find_services_by_name', service_name='ABC')['data']
    mock_get_services_by_partial_name.assert_called_once_with('ABC')
    assert len(response) == 2


def test_find_services_by_name_handles_no_results(admin_request, mocker):
    mock_get_services_by_partial_name = mocker.patch('app.service.rest.get_services_by_partial_name', return_value=[])
    response = admin_request.get('service.find_services_by_name', service_name='ZZZ')['data']
    mock_get_services_by_partial_name.assert_called_once_with('ZZZ')
    assert len(response) == 0


def test_find_services_by_name_handles_no_service_name(admin_request, mocker):
    mock_get_services_by_partial_name = mocker.patch('app.service.rest.get_services_by_partial_name')
    admin_request.get('service.find_services_by_name', _expected_status=400)
    mock_get_services_by_partial_name.assert_not_called()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_live_services_data(sample_user, admin_request, sample_service, sample_template):
    org = create_organisation()

    service = sample_service(go_live_user=sample_user, go_live_at=datetime(2018, 1, 1))
    service_2 = sample_service(service_name='second', go_live_at=datetime(2019, 1, 1), go_live_user=sample_user)

    template = sample_template(service=service)
    template2 = sample_template(service=service, template_type='email')
    dao_add_service_to_organisation(service=service, organisation_id=org.id)
    create_ft_billing(utc_date='2019-04-20', notification_type='sms', template=template, service=service)
    create_ft_billing(utc_date='2019-04-20', notification_type='email', template=template2, service=service)

    create_annual_billing(service.id, 1, 2019)
    create_annual_billing(service_2.id, 2, 2018)

    response = admin_request.get('service.get_live_services_data')['data']

    assert len(response) == 2
    assert response == [
        {
            'consent_to_research': None,
            'contact_email': 'notify@digital.cabinet-office.va.gov',
            'contact_mobile': '+16502532222',
            'contact_name': 'Test User',
            'email_totals': 1,
            'email_volume_intent': None,
            'letter_totals': 0,
            'letter_volume_intent': None,
            'live_date': 'Mon, 01 Jan 2018 00:00:00 GMT',
            'organisation_name': 'test_org_1',
            'service_id': ANY,
            'service_name': 'Sample service',
            'sms_totals': 1,
            'sms_volume_intent': None,
            'organisation_type': None,
            'free_sms_fragment_limit': 1,
        },
        {
            'consent_to_research': None,
            'contact_email': 'notify@digital.cabinet-office.va.gov',
            'contact_mobile': '+16502532222',
            'contact_name': 'Test User',
            'email_totals': 0,
            'email_volume_intent': None,
            'letter_totals': 0,
            'letter_volume_intent': None,
            'live_date': 'Tue, 01 Jan 2019 00:00:00 GMT',
            'organisation_name': None,
            'service_id': ANY,
            'service_name': 'second',
            'sms_totals': 0,
            'sms_volume_intent': None,
            'organisation_type': None,
            'free_sms_fragment_limit': 2,
        },
    ]


def test_get_service_by_id(admin_request, sample_service):
    service = sample_service()
    json_resp = admin_request.get('service.get_service_by_id', service_id=service.id)
    assert json_resp['data']['name'] == service.name
    assert json_resp['data']['id'] == str(service.id)
    assert not json_resp['data']['research_mode']
    assert json_resp['data']['email_branding'] is None
    assert 'branding' not in json_resp['data']
    assert json_resp['data']['prefix_sms'] is False


@pytest.mark.parametrize('detailed', [True, False])
def test_get_service_by_id_returns_organisation_type(admin_request, sample_service, detailed):
    json_resp = admin_request.get('service.get_service_by_id', service_id=sample_service().id, detailed=detailed)
    assert json_resp['data']['organisation_type'] == 'other'


def test_get_service_list_has_default_permissions(admin_request, sample_service, sample_user):
    user = sample_user()
    sample_service(user=user)
    sample_service(user=user)
    sample_service(user=user)
    sample_service(user=user)

    json_resp = admin_request.get('service.get_services')

    # user filter
    resp_data = [x for x in json_resp['data'] if x['created_by'] == str(user.id)]
    assert len(resp_data) == 4

    assert all((frozenset(json['permissions']) == frozenset(DEFAULT_SERVICE_PERMISSIONS)) for json in resp_data)


def test_get_service_by_id_has_default_service_permissions(admin_request, sample_service):
    json_resp = admin_request.get('service.get_service_by_id', service_id=sample_service().id)
    assert frozenset(json_resp['data']['permissions']) == frozenset(DEFAULT_SERVICE_PERMISSIONS)


def test_get_service_by_id_should_404_if_no_service(admin_request):
    json_resp = admin_request.get('service.get_service_by_id', service_id=uuid.uuid4(), _expected_status=404)

    assert json_resp['result'] == 'error'
    assert json_resp['message'] == 'No result found'


def test_get_service_by_id_and_user(client, sample_service, sample_user):
    user = sample_user()
    service = sample_service(user=user, email_from='something@service.com')

    auth_header = create_admin_authorization_header()
    resp = client.get('/service/{}?user_id={}'.format(service.id, user.id), headers=[auth_header])
    assert resp.status_code == 200
    json_resp = resp.json
    assert json_resp['data']['name'] == service.name
    assert json_resp['data']['id'] == str(service.id)


def test_get_service_by_id_should_404_if_no_service_for_user(notify_api, sample_user):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service_id = str(uuid.uuid4())
            auth_header = create_admin_authorization_header()
            resp = client.get('/service/{}?user_id={}'.format(service_id, sample_user().id), headers=[auth_header])
            assert resp.status_code == 404
            json_resp = resp.json
            assert json_resp['result'] == 'error'
            assert json_resp['message'] == 'No result found'


def test_get_service_by_id_returns_go_live_user_and_go_live_at(admin_request, sample_service, sample_user):
    now = datetime.utcnow()
    user = sample_user()
    service = sample_service(user=user, go_live_user=user, go_live_at=now)
    json_resp = admin_request.get('service.get_service_by_id', service_id=service.id)
    assert json_resp['data']['go_live_user'] == str(user.id)
    assert json_resp['data']['go_live_at'] == str(now)


@pytest.mark.parametrize(
    'platform_admin, expected_count_as_live',
    (
        (True, False),
        (False, True),
    ),
)
def test_create_service(
    admin_request,
    notify_db_session,
    sample_user,
    platform_admin,
    expected_count_as_live,
):
    user = sample_user(platform_admin=platform_admin)
    data = {
        'name': f'created service {uuid4()}',
        'user_id': str(user.id),
        'message_limit': 100,
        'restricted': False,
        'active': False,
        'email_from': f'created.service {uuid4()}',
        'created_by': str(user.id),
    }

    json_resp = admin_request.post('service.create_service', _data=data, _expected_status=201)

    assert json_resp['data']['id']
    assert json_resp['data']['name'] == data['name']
    assert json_resp['data']['email_from'] == data['email_from']
    assert not json_resp['data']['research_mode']
    assert json_resp['data']['rate_limit'] == 3000
    assert json_resp['data']['count_as_live'] is expected_count_as_live

    service = notify_db_session.session.get(Service, json_resp['data']['id'])
    assert service.name == data['name']

    json_resp = admin_request.get('service.get_service_by_id', service_id=json_resp['data']['id'], user_id=user.id)

    assert json_resp['data']['name'] == data['name']
    assert not json_resp['data']['research_mode']

    stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
    service_sms_senders = notify_db_session.session.scalars(stmt).all()
    assert len(service_sms_senders) == 1
    assert service_sms_senders[0].sms_sender == current_app.config['FROM_NUMBER']


@pytest.mark.skip(reason='We do not create services with default SMS senders anymore but will move this')
def test_create_service_with_valid_provider(admin_request, sample_user, ses_provider, current_sms_provider):
    user = sample_user()
    data = {
        'name': f'created service {uuid4()}',
        'user_id': str(user.id),
        'message_limit': 1000,
        'restricted': False,
        'active': False,
        'email_from': 'created.service',
        'created_by': str(user.id),
        'email_provider_id': str(ses_provider.id),
        'sms_provider_id': str(current_sms_provider.id),
    }

    json_resp = admin_request.post('service.create_service', _data=data, _expected_status=201)

    assert json_resp['data']['email_provider_id'] == str(ses_provider.id)
    assert json_resp['data']['sms_provider_id'] == str(current_sms_provider.id)

    service_db = Service.query.get(json_resp['data']['id'])
    assert service_db.name == 'created service'

    json_resp = admin_request.get('service.get_service_by_id', service_id=json_resp['data']['id'], user_id=user.id)

    assert json_resp['data']['email_provider_id'] == str(ses_provider.id)
    assert json_resp['data']['sms_provider_id'] == str(current_sms_provider.id)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'domain, expected_org',
    (
        (None, False),
        ('', False),
        ('unknown.va.gov', False),
        ('unknown-example.va.gov', False),
        ('example.va.gov', True),
        ('test.va.gov', True),
        ('test.example.va.gov', True),
    ),
)
def test_create_service_with_domain_sets_organisation(
    admin_request,
    sample_domain,
    sample_user,
    domain,
    expected_org,
):
    mixer = str(uuid4()).replace('-', '')
    mixed_domain = f'{domain}{mixer}'

    user = sample_user(email=f'test_@{mixed_domain}')
    red_herring_org = create_organisation(name='Sub example')
    sample_domain(f'specific.example.va.gov{mixer}', red_herring_org.id)
    sample_domain(f'aaaaaaaa.example.va.gov{mixer}', red_herring_org.id)

    org = create_organisation()

    sample_domain(f'example.va.gov{mixer}', org.id)
    sample_domain(f'test.va.gov{mixer}', org.id)

    another_org = create_organisation(name='Another')
    sample_domain(f'cabinet-office.va.gov{mixer}', another_org.id)
    sample_domain(f'cabinetoffice.va.gov{mixer}', another_org.id)

    data = {
        'name': f'created service {uuid4()}',
        'user_id': str(user.id),
        'message_limit': 1000,
        'restricted': False,
        'active': False,
        'created_by': str(user.id),
        'service_domain': mixed_domain,
    }

    json_resp = admin_request.post('service.create_service', _data=data, _expected_status=201)

    if expected_org:
        assert json_resp['data']['organisation'] == str(org.id)
    else:
        assert json_resp['data']['organisation'] is None


def test_should_not_create_service_with_missing_user_id_field(notify_api, fake_uuid):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                'email_from': 'service',
                'name': f'created service {uuid4()}',
                'message_limit': 1000,
                'restricted': False,
                'active': False,
                'created_by': str(fake_uuid),
            }
            auth_header = create_admin_authorization_header()
            headers = [('Content-Type', 'application/json'), auth_header]
            resp = client.post('/service', data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert resp.status_code == 400
            assert json_resp['result'] == 'error'
            assert 'Missing data for required field.' in json_resp['message']['user_id']


def test_should_error_if_created_by_missing(notify_api, sample_user):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                'email_from': 'service',
                'name': f'created service {uuid4()}',
                'message_limit': 1000,
                'restricted': False,
                'active': False,
                'user_id': str(sample_user().id),
            }
            auth_header = create_admin_authorization_header()
            headers = [('Content-Type', 'application/json'), auth_header]
            resp = client.post('/service', data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert resp.status_code == 400
            assert json_resp['result'] == 'error'
            assert 'Missing data for required field.' in json_resp['message']['created_by']


def test_should_not_create_service_with_missing_if_user_id_is_not_in_database(notify_api, fake_uuid):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                'email_from': 'service',
                'user_id': fake_uuid,
                'name': f'created service {uuid4()}',
                'message_limit': 1000,
                'restricted': False,
                'active': False,
                'created_by': str(fake_uuid),
            }
            auth_header = create_admin_authorization_header()
            headers = [('Content-Type', 'application/json'), auth_header]
            resp = client.post('/service', data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert resp.status_code == 404
            assert json_resp['result'] == 'error'
            assert json_resp['message'] == 'No result found'


def test_should_not_create_service_if_missing_data(notify_api, sample_user):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {'user_id': str(sample_user().id)}
            auth_header = create_admin_authorization_header()
            headers = [('Content-Type', 'application/json'), auth_header]
            resp = client.post('/service', data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert resp.status_code == 400
            assert json_resp['result'] == 'error'
            assert 'Missing data for required field.' in json_resp['message']['name']
            assert 'Missing data for required field.' in json_resp['message']['message_limit']
            assert 'Missing data for required field.' in json_resp['message']['restricted']


def test_should_not_create_service_with_duplicate_name(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            s1 = sample_service()
            data = {
                'name': s1.name,
                'user_id': str(s1.users[0].id),
                'message_limit': 1000,
                'restricted': False,
                'active': False,
                'email_from': 'sample.service2',
                'created_by': str(s1.users[0].id),
            }
            auth_header = create_admin_authorization_header()
            headers = [('Content-Type', 'application/json'), auth_header]
            resp = client.post('/service', data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert json_resp['result'] == 'error'
            assert "Duplicate service name '{}'".format(s1.name) in json_resp['message']['name']


@pytest.mark.parametrize('notification_type', (EMAIL_TYPE, SMS_TYPE))
def test_should_not_create_service_with_non_existent_provider(admin_request, sample_user, notification_type, fake_uuid):
    user = sample_user()
    data = {
        'name': f'created service {uuid4()}',
        'user_id': str(user.id),
        'message_limit': 1000,
        'restricted': False,
        'active': False,
        'email_from': 'created.service',
        'created_by': str(user.id),
        f'{notification_type}_provider_id': str(fake_uuid),
    }

    response = admin_request.post('service.create_service', _data=data, _expected_status=400)
    assert response['result'] == 'error'
    assert (
        response['message'][f'{notification_type}_provider_id'][0]
        == f'Invalid {notification_type}_provider_id: {str(fake_uuid)}'
    )


@pytest.mark.parametrize('notification_type', (EMAIL_TYPE, SMS_TYPE))
def test_should_not_create_service_with_inactive_provider(
    admin_request, sample_user, notification_type, fake_uuid, mocker
):
    user = sample_user()
    data = {
        'name': f'created service {uuid4()}',
        'user_id': str(user.id),
        'message_limit': 1000,
        'restricted': False,
        'active': False,
        'email_from': 'created.service',
        'created_by': str(user.id),
        f'{notification_type}_provider_id': str(fake_uuid),
    }

    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = False
    mocked_provider_details.notification_type = notification_type
    mocked_provider_details.id = fake_uuid
    mocker.patch('app.schemas.validate_providers.get_provider_details_by_id', return_value=mocked_provider_details)

    response = admin_request.post('service.create_service', _data=data, _expected_status=400)
    assert response['result'] == 'error'
    assert (
        response['message'][f'{notification_type}_provider_id'][0]
        == f'Invalid {notification_type}_provider_id: {str(fake_uuid)}'
    )


@pytest.mark.parametrize('notification_type', (EMAIL_TYPE, SMS_TYPE))
def test_should_not_create_service_with_incorrect_provider_notification_type(
    admin_request, sample_user, notification_type, fake_uuid, mocker
):
    user = sample_user()
    data = {
        'name': f'created service {uuid4()}',
        'user_id': str(user.id),
        'message_limit': 1000,
        'restricted': False,
        'active': False,
        'email_from': 'created.service',
        'created_by': str(user.id),
        f'{notification_type}_provider_id': str(fake_uuid),
    }

    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = False
    mocked_provider_details.notification_type = LETTER_TYPE
    mocked_provider_details.id = fake_uuid
    mocker.patch('app.schemas.validate_providers.get_provider_details_by_id', return_value=mocked_provider_details)

    response = admin_request.post('service.create_service', _data=data, _expected_status=400)
    assert response['result'] == 'error'
    assert (
        response['message'][f'{notification_type}_provider_id'][0]
        == f'Invalid {notification_type}_provider_id: {str(fake_uuid)}'
    )


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_service(client, notify_db, sample_service):
    brand = EmailBranding(colour='#000000', logo='justice-league.png', name=f'Justice League {uuid4()}')
    notify_db.session.add(brand)
    notify_db.session.commit()
    service = sample_service()
    assert service.email_branding is None

    data = {
        'name': f'updated service name {uuid4()}',
        'email_from': 'updated.service.name',
        'created_by': str(service.created_by.id),
        'email_branding': str(brand.id),
        'organisation_type': 'other',
    }

    auth_header = create_admin_authorization_header()

    resp = client.post(
        '/service/{}'.format(service.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    result = resp.json
    assert resp.status_code == 200
    assert result['data']['name'] == data['name']
    assert result['data']['email_from'] == 'updated.service.name'
    assert result['data']['email_branding'] == str(brand.id)
    assert result['data']['organisation_type'] == 'other'


@pytest.mark.serial  # intermittent
def test_update_service_with_valid_provider(notify_api, admin_request, notify_db_session, sample_provider, sample_service,):
    data = {
        'email_provider_id': str(sample_provider(str(uuid.uuid4()), notification_type=EMAIL_TYPE).id),
        'sms_provider_id': str(sample_provider(str(uuid.uuid4())).id),
    }

    resp = admin_request.post(
        'service.update_service', service_id=sample_service().id, _data=data, _expected_status=200
    )
    assert resp['data']['email_provider_id'] == data['email_provider_id']
    assert resp['data']['sms_provider_id'] == data['sms_provider_id']

    service_db = notify_db_session.session.get(Service, resp['data']['id'])

    assert str(service_db.email_provider_id) == data['email_provider_id']
    assert str(service_db.sms_provider_id) == data['sms_provider_id']


@pytest.mark.parametrize('notification_type', (EMAIL_TYPE, SMS_TYPE))
def test_should_not_update_service_with_inactive_provider(
    admin_request, notification_type, sample_service, fake_uuid, mocker
):
    data = {f'{notification_type}_provider_id': str(fake_uuid)}

    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = False
    mocked_provider_details.notification_type = notification_type
    mocked_provider_details.id = fake_uuid
    mocker.patch('app.schemas.validate_providers.get_provider_details_by_id', return_value=mocked_provider_details)

    response = admin_request.post(
        'service.update_service', service_id=sample_service().id, _data=data, _expected_status=400
    )
    assert response['result'] == 'error'
    assert (
        response['message'][f'{notification_type}_provider_id'][0]
        == f'Invalid {notification_type}_provider_id: {str(fake_uuid)}'
    )


@pytest.mark.parametrize('notification_type', (EMAIL_TYPE, SMS_TYPE))
def test_should_not_update_service_with_incorrect_provider_notification_type(
    admin_request, notification_type, sample_service, fake_uuid, mocker
):
    data = {f'{notification_type}_provider_id': str(fake_uuid)}

    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = False
    mocked_provider_details.notification_type = LETTER_TYPE
    mocked_provider_details.id = fake_uuid
    mocker.patch('app.schemas.validate_providers.get_provider_details_by_id', return_value=mocked_provider_details)

    response = admin_request.post(
        'service.update_service', service_id=sample_service().id, _data=data, _expected_status=400
    )
    assert response['result'] == 'error'
    assert (
        response['message'][f'{notification_type}_provider_id'][0]
        == f'Invalid {notification_type}_provider_id: {str(fake_uuid)}'
    )


@pytest.mark.parametrize('notification_type', (EMAIL_TYPE, SMS_TYPE))
def test_should_not_update_service_with_nonexistent_provider(
    admin_request, notification_type, sample_service, fake_uuid
):
    data = {f'{notification_type}_provider_id': str(fake_uuid)}

    response = admin_request.post(
        'service.update_service', service_id=sample_service().id, _data=data, _expected_status=400
    )
    assert response['result'] == 'error'
    assert (
        response['message'][f'{notification_type}_provider_id'][0]
        == f'Invalid {notification_type}_provider_id: {str(fake_uuid)}'
    )


def test_cant_update_service_org_type_to_random_value(client, sample_service):
    service = sample_service()
    data = {
        'name': 'updated service name',
        'email_from': 'updated.service.name',
        'created_by': str(service.created_by.id),
        'organisation_type': 'foo',
    }

    auth_header = create_admin_authorization_header()

    resp = client.post(
        '/service/{}'.format(service.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert resp.status_code == 500


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_service_remove_email_branding(admin_request, notify_db_session, sample_service):
    brand = EmailBranding(colour='#000000', logo='justice-league.png', name='Justice League')
    service = sample_service()
    service.email_branding = brand
    notify_db_session.session.commit()

    resp = admin_request.post('service.update_service', service_id=service.id, _data={'email_branding': None})
    assert resp['data']['email_branding'] is None


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_service_change_email_branding(admin_request, notify_db_session, sample_service):
    brand1 = EmailBranding(colour='#000000', logo='justice-league.png', name='Justice League')
    brand2 = EmailBranding(colour='#111111', logo='avengers.png', name='Avengers')
    notify_db_session.session.add_all([brand1, brand2])
    service = sample_service()
    service.email_branding = brand1
    notify_db_session.session.commit()

    resp = admin_request.post('service.update_service', service_id=service.id, _data={'email_branding': str(brand2.id)})
    assert resp['data']['email_branding'] == str(brand2.id)


def test_update_service_flags(client, sample_service):
    service = sample_service()
    auth_header = create_admin_authorization_header()
    resp = client.get('/service/{}'.format(service.id), headers=[auth_header])
    json_resp = resp.json
    assert resp.status_code == 200
    assert json_resp['data']['name'] == service.name
    assert json_resp['data']['research_mode'] is False

    data = {'research_mode': True, 'permissions': [LETTER_TYPE, INTERNATIONAL_SMS_TYPE]}

    auth_header = create_admin_authorization_header()

    resp = client.post(
        '/service/{}'.format(service.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    result = resp.json
    assert resp.status_code == 200
    assert result['data']['research_mode'] is True
    assert set(result['data']['permissions']) == set([LETTER_TYPE, INTERNATIONAL_SMS_TYPE])


@pytest.mark.parametrize(
    'field',
    (
        'volume_email',
        'volume_sms',
        'volume_letter',
    ),
)
@pytest.mark.parametrize(
    'value, expected_status, expected_persisted',
    (
        (1234, 200, 1234),
        (None, 200, None),
        ('Aa', 400, None),
    ),
)
def test_update_service_sets_volumes(
    admin_request,
    sample_service,
    field,
    value,
    expected_status,
    expected_persisted,
):
    service = sample_service()
    admin_request.post(
        'service.update_service',
        service_id=service.id,
        _data={
            field: value,
        },
        _expected_status=expected_status,
    )
    assert getattr(service, field) == expected_persisted


@pytest.mark.parametrize(
    'value, expected_status, expected_persisted',
    (
        (True, 200, True),
        (False, 200, False),
        ('Yes', 400, None),
    ),
)
def test_update_service_sets_research_consent(
    admin_request,
    sample_service,
    value,
    expected_status,
    expected_persisted,
):
    service = sample_service()
    assert service.consent_to_research is None
    admin_request.post(
        'service.update_service',
        service_id=service.id,
        _data={
            'consent_to_research': value,
        },
        _expected_status=expected_status,
    )
    assert service.consent_to_research is expected_persisted


def test_update_service_flags_with_service_without_default_service_permissions(client, sample_service):
    service = sample_service(service_permissions=[])
    auth_header = create_admin_authorization_header()
    data = {
        'permissions': [LETTER_TYPE, INTERNATIONAL_SMS_TYPE],
    }

    resp = client.post(
        '/service/{}'.format(service.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    result = resp.json

    assert resp.status_code == 200
    assert set(result['data']['permissions']) == set([LETTER_TYPE, INTERNATIONAL_SMS_TYPE])


def test_update_service_flags_will_remove_service_permissions(client, sample_service):
    auth_header = create_admin_authorization_header()

    service = sample_service(service_permissions=[SMS_TYPE, EMAIL_TYPE, INTERNATIONAL_SMS_TYPE])

    assert INTERNATIONAL_SMS_TYPE in [p.permission for p in service.permissions]

    data = {'permissions': [SMS_TYPE, EMAIL_TYPE]}

    resp = client.post(
        '/service/{}'.format(service.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    result = resp.json

    assert resp.status_code == 200
    assert INTERNATIONAL_SMS_TYPE not in result['data']['permissions']

    permissions = ServicePermission.query.filter_by(service_id=service.id).all()
    assert set([p.permission for p in permissions]) == set([SMS_TYPE, EMAIL_TYPE])


def test_update_permissions_will_override_permission_flags(client, sample_service):
    service = sample_service(service_permissions=[])
    auth_header = create_admin_authorization_header()

    data = {'permissions': [LETTER_TYPE, INTERNATIONAL_SMS_TYPE]}

    resp = client.post(
        '/service/{}'.format(service.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    result = resp.json

    assert resp.status_code == 200
    assert set(result['data']['permissions']) == set([LETTER_TYPE, INTERNATIONAL_SMS_TYPE])


def test_update_service_permissions_will_add_service_permissions(client, sample_service):
    auth_header = create_admin_authorization_header()

    data = {'permissions': [EMAIL_TYPE, SMS_TYPE, LETTER_TYPE]}

    resp = client.post(
        '/service/{}'.format(sample_service().id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    result = resp.json

    assert resp.status_code == 200
    assert set(result['data']['permissions']) == set([SMS_TYPE, EMAIL_TYPE, LETTER_TYPE])


@pytest.mark.parametrize(
    'permission_to_add',
    [
        (EMAIL_TYPE),
        (SMS_TYPE),
        (INTERNATIONAL_SMS_TYPE),
        (LETTER_TYPE),
        (INBOUND_SMS_TYPE),
    ],
)
def test_add_service_permission_will_add_permission(client, notify_db_session, sample_service, permission_to_add):
    service = sample_service(service_permissions=[])
    auth_header = create_admin_authorization_header()

    data = {'permissions': [permission_to_add]}

    resp = client.post(
        '/service/{}'.format(service.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    stmt = (
        select(ServicePermission)
        .where(ServicePermission.service_id == service.id)
        .where(ServicePermission.permission == permission_to_add)
    )
    permissions = notify_db_session.session.scalars(stmt).all()

    assert resp.status_code == 200
    assert [p.permission for p in permissions] == [permission_to_add]


def test_update_permissions_with_an_invalid_permission_will_raise_error(client, sample_service):
    auth_header = create_admin_authorization_header()
    invalid_permission = 'invalid_permission'

    data = {'permissions': [EMAIL_TYPE, SMS_TYPE, invalid_permission]}

    resp = client.post(
        '/service/{}'.format(sample_service().id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    result = resp.json

    assert resp.status_code == 400
    assert result['result'] == 'error'
    assert "Invalid Service Permission: '{}'".format(invalid_permission) in result['message']['permissions']


def test_update_permissions_with_duplicate_permissions_will_raise_error(client, sample_service):
    auth_header = create_admin_authorization_header()

    data = {'permissions': [EMAIL_TYPE, SMS_TYPE, LETTER_TYPE, LETTER_TYPE]}

    resp = client.post(
        '/service/{}'.format(sample_service().id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    result = resp.json

    assert resp.status_code == 400
    assert result['result'] == 'error'
    assert "Duplicate Service Permission: ['{}']".format(LETTER_TYPE) in result['message']['permissions']


def test_update_service_research_mode_throws_validation_error(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service = sample_service()
            auth_header = create_admin_authorization_header()
            resp = client.get('/service/{}'.format(service.id), headers=[auth_header])
            json_resp = resp.json
            assert resp.status_code == 200
            assert json_resp['data']['name'] == service.name
            assert not json_resp['data']['research_mode']

            data = {'research_mode': 'dedede'}

            auth_header = create_admin_authorization_header()

            resp = client.post(
                '/service/{}'.format(service.id),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            result = resp.json
            assert result['message']['research_mode'][0] == 'Not a valid boolean.'
            assert resp.status_code == 400


def test_should_not_update_service_with_duplicate_name(notify_api, sample_service):
    # Create two services and attempt to update one to the other's name
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service_name = f'another name {uuid4()}'
            # First service, created with service_name
            sample_service(service_name=service_name, email_from=f'another.name {uuid4()}')

            service_to_update = sample_service()
            data = {
                'name': service_name,
            }

            auth_header = create_admin_authorization_header()

            # Updating second service with service_name
            resp = client.post(
                '/service/{}'.format(service_to_update.id),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            # Failure is expected
            assert resp.status_code == 400
            json_resp = resp.json
            assert json_resp['result'] == 'error'
            assert "Duplicate service name '{}'".format(service_name) in json_resp['message']['name']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_should_not_update_service_with_duplicate_email_from(notify_api, sample_service):
    # No services in any environment use email_from
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            email_from = f'duplicate.name {uuid4()}'
            # Original and duplicate (email_from) services
            sample_service(email_from=email_from)
            duplicate = sample_service(email_from='random')
            data = {'name': duplicate.name, 'email_from': email_from, 'created_by': str(duplicate.created_by.id)}

            auth_header = create_admin_authorization_header()

            resp = client.post(
                '/service/{}'.format(duplicate.id),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert resp.status_code == 400
            json_resp = resp.json
            assert json_resp['result'] == 'error'
            assert "Duplicate service email_from '{}'".format(email_from) in json_resp['message']['email_from']


def test_update_service_should_404_if_id_is_invalid(notify_api):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {'name': 'updated service name'}

            missing_service_id = uuid.uuid4()

            auth_header = create_admin_authorization_header()

            resp = client.post(
                '/service/{}'.format(missing_service_id),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert resp.status_code == 404


def test_get_users_by_service(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service = sample_service()
            user_on_service = service.users[0]
            auth_header = create_admin_authorization_header()

            resp = client.get(
                '/service/{}/users'.format(service.id), headers=[('Content-Type', 'application/json'), auth_header]
            )

            assert resp.status_code == 200
            result = resp.json
            assert len(result['data']) == 1
            assert result['data'][0]['name'] == user_on_service.name
            assert result['data'][0]['email_address'] == user_on_service.email_address
            assert result['data'][0]['mobile_number'] == user_on_service.mobile_number


def test_get_users_for_service_returns_empty_list_if_no_users_associated_with_service(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service = sample_service()
            dao_remove_user_from_service(service, service.users[0])
            auth_header = create_admin_authorization_header()

            response = client.get(
                '/service/{}/users'.format(service.id), headers=[('Content-Type', 'application/json'), auth_header]
            )
            result = response.get_json()
            assert response.status_code == 200
            assert result['data'] == []


def test_get_users_for_service_returns_404_when_service_does_not_exist(notify_api):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service_id = uuid.uuid4()
            auth_header = create_admin_authorization_header()

            response = client.get(
                '/service/{}/users'.format(service_id), headers=[('Content-Type', 'application/json'), auth_header]
            )
            assert response.status_code == 404
            result = response.get_json()
            assert result['result'] == 'error'
            assert result['message'] == 'No result found'


def test_default_permissions_are_added_for_user_service(notify_api, sample_user):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            user = sample_user()
            data = {
                'name': f'created service {uuid4()}',
                'user_id': str(user.id),
                'message_limit': 1000,
                'restricted': False,
                'active': False,
                'email_from': 'created.service',
                'created_by': str(user.id),
            }
            auth_header = create_admin_authorization_header()
            headers = [('Content-Type', 'application/json'), auth_header]
            resp = client.post('/service', data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert resp.status_code == 201
            assert json_resp['data']['id']
            service_0_id = json_resp['data']['id']
            assert json_resp['data']['name'] == data['name']
            assert json_resp['data']['email_from'] == 'created.service'

            auth_header_fetch = create_admin_authorization_header()

            resp = client.get(
                '/service/{}?user_id={}'.format(json_resp['data']['id'], user.id), headers=[auth_header_fetch]
            )
            assert resp.status_code == 200
            header = create_admin_authorization_header()
            response = client.get(url_for('user.get_user', user_id=user.id), headers=[header])
            assert response.status_code == 200
            json_resp = response.get_json()
            service_permissions = json_resp['data']['permissions'][service_0_id]
            from app.dao.permissions_dao import default_service_permissions

            assert sorted(default_service_permissions) == sorted(service_permissions)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_existing_user_to_another_service_with_all_permissions(
    notify_api,
    sample_service,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            # check which users part of service
            service = sample_service()
            user_already_in_service = service.users[0]
            auth_header = create_admin_authorization_header()

            resp = client.get(
                '/service/{}/users'.format(service.id), headers=[('Content-Type', 'application/json'), auth_header]
            )

            assert resp.status_code == 200
            result = resp.json
            assert len(result['data']) == 1
            assert result['data'][0]['email_address'] == user_already_in_service.email_address

            # add new user to service
            user_to_add = User(  # nosec
                name='Invited User',
                email_address='invited@digital.cabinet-office.va.gov',
                password='password',
                mobile_number='+4477123456',
            )
            # they must exist in db first
            save_model_user(user_to_add)

            data = {
                'permissions': [
                    {'permission': 'send_emails'},
                    {'permission': 'send_letters'},
                    {'permission': 'send_texts'},
                    {'permission': 'manage_users'},
                    {'permission': 'manage_settings'},
                    {'permission': 'manage_api_keys'},
                    {'permission': 'manage_templates'},
                    {'permission': 'view_activity'},
                ],
                'folder_permissions': [],
            }

            auth_header = create_admin_authorization_header()

            resp = client.post(
                '/service/{}/users/{}'.format(service.id, user_to_add.id),
                headers=[('Content-Type', 'application/json'), auth_header],
                data=json.dumps(data),
            )

            assert resp.status_code == 201

            # check new user added to service
            auth_header = create_admin_authorization_header()

            resp = client.get(
                '/service/{}'.format(service.id),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert resp.status_code == 200
            json_resp = resp.json
            assert str(user_to_add.id) in json_resp['data']['users']

            # check user has all permissions
            auth_header = create_admin_authorization_header()
            resp = client.get(
                url_for('user.get_user', user_id=user_to_add.id),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            assert resp.status_code == 200
            json_resp = resp.json
            permissions = json_resp['data']['permissions'][str(service.id)]
            expected_permissions = [
                'send_texts',
                'send_emails',
                'send_letters',
                'manage_users',
                'manage_settings',
                'manage_templates',
                'manage_api_keys',
                'view_activity',
            ]
            assert sorted(expected_permissions) == sorted(permissions)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_existing_user_to_another_service_with_send_permissions(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            # they must exist in db first
            user_to_add = User(  # nosec
                name='Invited User',
                email_address='invited@digital.cabinet-office.va.gov',
                password='password',
                mobile_number='+4477123456',
            )
            save_model_user(user_to_add)

            data = {
                'permissions': [
                    {'permission': 'send_emails'},
                    {'permission': 'send_letters'},
                    {'permission': 'send_texts'},
                ],
                'folder_permissions': [],
            }

            auth_header = create_admin_authorization_header()

            resp = client.post(
                '/service/{}/users/{}'.format(sample_service.id, user_to_add.id),
                headers=[('Content-Type', 'application/json'), auth_header],
                data=json.dumps(data),
            )

            assert resp.status_code == 201

            # check user has send permissions
            auth_header = create_admin_authorization_header()
            resp = client.get(
                url_for('user.get_user', user_id=user_to_add.id),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            assert resp.status_code == 200
            json_resp = resp.json

            permissions = json_resp['data']['permissions'][str(sample_service.id)]
            expected_permissions = ['send_texts', 'send_emails', 'send_letters']
            assert sorted(expected_permissions) == sorted(permissions)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_existing_user_to_another_service_with_manage_permissions(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            # they must exist in db first
            user_to_add = User(  # nosec
                name='Invited User',
                email_address='invited@digital.cabinet-office.va.gov',
                password='password',
                mobile_number='+4477123456',
            )
            save_model_user(user_to_add)

            data = {
                'permissions': [
                    {'permission': 'manage_users'},
                    {'permission': 'manage_settings'},
                    {'permission': 'manage_templates'},
                ]
            }

            auth_header = create_admin_authorization_header()

            resp = client.post(
                '/service/{}/users/{}'.format(sample_service.id, user_to_add.id),
                headers=[('Content-Type', 'application/json'), auth_header],
                data=json.dumps(data),
            )

            assert resp.status_code == 201

            # check user has send permissions
            auth_header = create_admin_authorization_header()
            resp = client.get(
                url_for('user.get_user', user_id=user_to_add.id),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            assert resp.status_code == 200
            json_resp = resp.json

            permissions = json_resp['data']['permissions'][str(sample_service.id)]
            expected_permissions = ['manage_users', 'manage_settings', 'manage_templates']
            assert sorted(expected_permissions) == sorted(permissions)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_existing_user_to_another_service_with_folder_permissions(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            # they must exist in db first
            user_to_add = User(  # nosec
                name='Invited User',
                email_address='invited@digital.cabinet-office.va.gov',
                password='password',
                mobile_number='+4477123456',
            )
            save_model_user(user_to_add)

            folder_1 = create_template_folder(sample_service)
            folder_2 = create_template_folder(sample_service)

            data = {
                'permissions': [{'permission': 'manage_api_keys'}],
                'folder_permissions': [str(folder_1.id), str(folder_2.id)],
            }

            auth_header = create_admin_authorization_header()

            resp = client.post(
                '/service/{}/users/{}'.format(sample_service.id, user_to_add.id),
                headers=[('Content-Type', 'application/json'), auth_header],
                data=json.dumps(data),
            )

            assert resp.status_code == 201

            new_user = dao_get_service_user(user_id=user_to_add.id, service_id=sample_service.id)

            assert len(new_user.folders) == 2
            assert folder_1 in new_user.folders
            assert folder_2 in new_user.folders


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_existing_user_to_another_service_with_manage_api_keys(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            # they must exist in db first
            user_to_add = User(  # nosec
                name='Invited User',
                email_address='invited@digital.cabinet-office.va.gov',
                password='password',
                mobile_number='+4477123456',
            )
            save_model_user(user_to_add)

            data = {'permissions': [{'permission': 'manage_api_keys'}]}

            auth_header = create_admin_authorization_header()

            resp = client.post(
                '/service/{}/users/{}'.format(sample_service.id, user_to_add.id),
                headers=[('Content-Type', 'application/json'), auth_header],
                data=json.dumps(data),
            )

            assert resp.status_code == 201

            # check user has send permissions
            auth_header = create_admin_authorization_header()
            resp = client.get(
                url_for('user.get_user', user_id=user_to_add.id),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            assert resp.status_code == 200
            json_resp = resp.json

            permissions = json_resp['data']['permissions'][str(sample_service.id)]
            expected_permissions = ['manage_api_keys']
            assert sorted(expected_permissions) == sorted(permissions)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_existing_user_to_non_existing_service_returns404(notify_api):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            user_to_add = User(  # nosec
                name='Invited User',
                email_address='invited@digital.cabinet-office.va.gov',
                password='password',
                mobile_number='+4477123456',
            )
            save_model_user(user_to_add)

            incorrect_id = uuid.uuid4()

            data = {'permissions': ['send_messages', 'manage_service', 'manage_api_keys']}
            auth_header = create_admin_authorization_header()

            resp = client.post(
                '/service/{}/users/{}'.format(incorrect_id, user_to_add.id),
                headers=[('Content-Type', 'application/json'), auth_header],
                data=json.dumps(data),
            )

            result = resp.json
            expected_message = 'No result found'

            assert resp.status_code == 404
            assert result['result'] == 'error'
            assert result['message'] == expected_message


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_existing_user_of_service_to_service_returns400(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service = sample_service()
            existing_user_id = service.users[0].id

            data = {'permissions': ['send_messages', 'manage_service', 'manage_api_keys']}
            auth_header = create_admin_authorization_header()

            resp = client.post(
                '/service/{}/users/{}'.format(service.id, existing_user_id),
                headers=[('Content-Type', 'application/json'), auth_header],
                data=json.dumps(data),
            )

            result = resp.json
            expected_message = 'User id: {} already part of service id: {}'.format(existing_user_id, service.id)

            assert resp.status_code == 400
            assert result['result'] == 'error'
            assert result['message'] == expected_message


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_unknown_user_to_service_returns404(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            incorrect_id = 9876

            data = {'permissions': ['send_messages', 'manage_service', 'manage_api_keys']}
            auth_header = create_admin_authorization_header()

            resp = client.post(
                '/service/{}/users/{}'.format(sample_service().id, incorrect_id),
                headers=[('Content-Type', 'application/json'), auth_header],
                data=json.dumps(data),
            )

            result = resp.json
            expected_message = 'No result found'

            assert resp.status_code == 404
            assert result['result'] == 'error'
            assert result['message'] == expected_message


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_remove_user_from_service(client, sample_user, sample_user_service_permission):
    second_user = sample_user(email='new@digital.cabinet-office.va.gov')
    service = sample_user_service_permission.service

    # Simulates successfully adding a user to the service
    dao_add_user_to_service(
        service,
        second_user,
        permissions=[Permission(service_id=service.id, user_id=second_user.id, permission='manage_settings')],
    )

    endpoint = url_for('service.remove_user_from_service', service_id=str(service.id), user_id=str(second_user.id))
    auth_header = create_admin_authorization_header()
    resp = client.delete(endpoint, headers=[('Content-Type', 'application/json'), auth_header])
    assert resp.status_code == 204


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_remove_non_existant_user_from_service(client, sample_user, sample_user_service_permission):
    second_user = sample_user(email='new@digital.cabinet-office.va.gov')
    endpoint = url_for(
        'service.remove_user_from_service',
        service_id=str(sample_user_service_permission.service.id),
        user_id=str(second_user.id),
    )
    auth_header = create_admin_authorization_header()
    resp = client.delete(endpoint, headers=[('Content-Type', 'application/json'), auth_header])
    assert resp.status_code == 404


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_cannot_remove_only_user_from_service(notify_api, sample_user_service_permission):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            endpoint = url_for(
                'service.remove_user_from_service',
                service_id=str(sample_user_service_permission.service.id),
                user_id=str(sample_user_service_permission.user.id),
            )
            auth_header = create_admin_authorization_header()
            resp = client.delete(endpoint, headers=[('Content-Type', 'application/json'), auth_header])
            assert resp.status_code == 400
            result = resp.json
            assert result['message'] == 'You cannot remove the only user for a service'


# This test is just here verify get_service_and_api_key_history that is a temp solution
# until proper ui is sorted out on admin app
def test_get_service_and_api_key_history(notify_api, sample_service, sample_api_key):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service = sample_service()
            api_key = sample_api_key(service=service)

            auth_header = create_admin_authorization_header()
            response = client.get(path='/service/{}/history'.format(service.id), headers=[auth_header])
            assert response.status_code == 200

            json_resp = response.get_json()
            assert json_resp['data']['service_history'][0]['id'] == str(service.id)
            assert json_resp['data']['api_key_history'][0]['id'] == str(api_key.id)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_all_notifications_for_service_in_order(notify_api, notify_db_session, sample_service, sample_template):
    with notify_api.test_request_context(), notify_api.test_client() as client:
        service_1 = sample_service()
        service_2 = sample_service()

        service_1_template = sample_template(service_1)
        service_2_template = sample_template(service_2)

        # create notification for service_2
        s2_notification = create_notification(service_2_template)

        notification_1 = create_notification(service_1_template)
        notification_2 = create_notification(service_1_template)
        notification_3 = create_notification(service_1_template)

        auth_header = create_admin_authorization_header()

        response = client.get(path='/service/{}/notifications'.format(service_1.id), headers=[auth_header])

        resp = response.get_json()
        assert len(resp['notifications']) == 3
        assert resp['notifications'][0]['to'] == notification_3.to
        assert resp['notifications'][1]['to'] == notification_2.to
        assert resp['notifications'][2]['to'] == notification_1.to
        assert response.status_code == 200

        # Teardown
        notify_db_session.session.delete(s2_notification)
        notify_db_session.session.delete(notification_1)
        notify_db_session.session.delete(notification_2)
        notify_db_session.session.delete(notification_3)
        notify_db_session.session.commit()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_all_notifications_for_service_formatted_for_csv(client, sample_template):
    notification = create_notification(template=sample_template)
    auth_header = create_admin_authorization_header()

    response = client.get(
        path='/service/{}/notifications?format_for_csv=True'.format(sample_template.service_id), headers=[auth_header]
    )

    resp = response.get_json()
    assert response.status_code == 200
    assert len(resp['notifications']) == 1
    assert resp['notifications'][0]['recipient'] == notification.to
    assert not resp['notifications'][0]['row_number']
    assert resp['notifications'][0]['template_name'] == sample_template.name
    assert resp['notifications'][0]['template_type'] == notification.notification_type
    assert resp['notifications'][0]['status'] == 'Sending'


def test_get_notification_for_service_without_uuid(
    client,
    sample_service,
):
    service = sample_service()
    response = client.get(
        path='/service/{}/notifications/{}'.format(service.id, 'foo'), headers=[create_admin_authorization_header()]
    )
    assert response.status_code == 404


def test_get_notification_for_service(
    client,
    sample_api_key,
    sample_notification,
    sample_service,
    sample_template,
):
    service_1 = sample_service()
    service_2 = sample_service()
    api_key_1 = sample_api_key(service=service_1)
    api_key_2 = sample_api_key(service=service_2)

    service_1_template = sample_template(service=service_1)
    service_2_template = sample_template(service=service_2)

    s1_notifications = [
        sample_notification(template=service_1_template, api_key=api_key_1),
        sample_notification(template=service_1_template, api_key=api_key_1),
        sample_notification(template=service_1_template, api_key=api_key_1),
    ]

    sample_notification(template=service_2_template, api_key=api_key_2)

    for notification in s1_notifications:
        response = client.get(
            path='/service/{}/notifications/{}'.format(service_1.id, notification.id),
            headers=[create_admin_authorization_header()],
        )
        resp = response.get_json()
        assert str(resp['id']) == str(notification.id)
        assert response.status_code == 200

        service_2_response = client.get(
            path='/service/{}/notifications/{}'.format(service_2.id, notification.id),
            headers=[create_admin_authorization_header()],
        )
        assert service_2_response.status_code == 404
        service_2_response = json.loads(service_2_response.get_data(as_text=True))
        assert service_2_response == {'message': 'No result found', 'result': 'error'}


def test_get_notification_for_service_includes_created_by(
    admin_request,
    sample_api_key,
    sample_notification,
    sample_template,
):
    template = sample_template()
    api_key = sample_api_key(service=template.service)

    notification = sample_notification(template=template, api_key=api_key)
    notification_user = notification.created_by

    resp = admin_request.get(
        'service.get_notification_for_service', service_id=notification.service_id, notification_id=notification.id
    )

    assert resp['id'] == str(notification.id)
    assert resp['created_by'] == {
        'id': str(notification_user.id),
        'name': notification_user.name,
        'email_address': notification_user.email_address,
    }


def test_get_notification_for_service_returns_old_template_version(
    admin_request,
    sample_api_key,
    sample_notification,
    sample_template,
):
    template = sample_template()
    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, api_key=api_key)
    notification.reference = 'modified-inplace'
    template.version = 2
    template.content = 'New template content'

    resp = admin_request.get(
        'service.get_notification_for_service', service_id=notification.service_id, notification_id=notification.id
    )

    assert resp['reference'] == 'modified-inplace'
    assert resp['template']['version'] == 1
    assert resp['template']['content'] == notification.template.content
    assert resp['template']['content'] != template.content


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize('include_from_test_key, expected_count_of_notifications', [(False, 2), (True, 3)])
def test_get_all_notifications_for_service_including_ones_made_by_jobs(
    client,
    notify_db_session,
    sample_service,
    include_from_test_key,
    expected_count_of_notifications,
    sample_notification,
    sample_notification_with_job,
    sample_template,
):
    # notification from_test_api_key
    notification = sample_notification(sample_template, key_type=KEY_TYPE_TEST)

    auth_header = create_admin_authorization_header()

    response = client.get(
        path='/service/{}/notifications?include_from_test_key={}'.format(sample_service.id, include_from_test_key),
        headers=[auth_header],
    )

    resp = response.get_json()
    assert len(resp['notifications']) == expected_count_of_notifications
    assert resp['notifications'][0]['to'] == sample_notification_with_job.to
    assert resp['notifications'][1]['to'] == notification.to
    assert response.status_code == 200

    # Teardown
    notify_db_session.session.delete(notification)
    notify_db_session.session.commit()


def test_get_only_api_created_notifications_for_service(
    admin_request,
    sample_api_key,
    sample_notification,
    sample_template,
):
    template = sample_template()
    api_key = sample_api_key(service=template.service)
    # notification sent as a one-off
    sample_notification(template=template, one_off=True, api_key=api_key)
    # notification sent via API
    without_job = sample_notification(template=template, api_key=api_key, created_by_id=None)

    resp = admin_request.get(
        'service.get_all_notifications_for_service',
        service_id=template.service_id,
        include_jobs=False,
        include_one_off=False,
    )
    assert len(resp['notifications']) == 1
    assert resp['notifications'][0]['id'] == str(without_job.id)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_notifications_for_service_without_page_count(
    admin_request,
    sample_template,
):
    create_notification(sample_template)
    without_job = create_notification(sample_template)

    resp = admin_request.get(
        'service.get_all_notifications_for_service',
        service_id=sample_template.service_id,
        page_size=1,
        include_jobs=False,
        include_one_off=False,
        count_pages=False,
    )
    assert len(resp['notifications']) == 1
    assert resp['total'] is None
    assert resp['notifications'][0]['id'] == str(without_job.id)


@pytest.mark.parametrize(
    'should_prefix',
    [
        True,
        False,
    ],
)
def test_prefixing_messages_based_on_prefix_sms(
    client,
    sample_service,
    should_prefix,
):
    service = sample_service(prefix_sms=should_prefix)

    result = client.get(
        url_for('service.get_service_by_id', service_id=service.id),
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
    )
    service = json.loads(result.get_data(as_text=True))['data']
    assert service['prefix_sms'] == should_prefix


@pytest.mark.parametrize(
    'posted_value, stored_value, returned_value',
    [
        (True, True, True),
        (False, False, False),
    ],
)
def test_set_sms_prefixing_for_service(
    admin_request,
    client,
    sample_service,
    posted_value,
    stored_value,
    returned_value,
):
    result = admin_request.post(
        'service.update_service',
        service_id=sample_service().id,
        _data={'prefix_sms': posted_value},
    )
    assert result['data']['prefix_sms'] == stored_value


def test_set_sms_prefixing_for_service_cant_be_none(
    admin_request,
    sample_service,
):
    resp = admin_request.post(
        'service.update_service',
        service_id=sample_service().id,
        _data={'prefix_sms': None},
        _expected_status=400,
    )
    assert resp['message'] == {'prefix_sms': ['Field may not be null.']}


# This always returns 0. Does not appear to be used
@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'today_only,stats',
    [('False', {'requested': 2, 'delivered': 1, 'failed': 0}), ('True', {'requested': 1, 'delivered': 0, 'failed': 0})],
    ids=['seven_days', 'today'],
)
def test_get_detailed_service(notify_api, notify_db_session, sample_service, sample_template, today_only, stats):
    with notify_api.test_request_context(), notify_api.test_client() as client:
        service = sample_service()
        template = sample_template()
        ft_notification = create_ft_notification_status(date(2000, 1, 2), 'sms', template=template, count=1)
        with freeze_time('2000-01-02T12:00:00'):
            notification_0 = create_notification(template=template, status='created')
            notification_1 = create_notification(template=template, status='created')
            resp = client.get(
                '/service/{}?detailed=True&today_only={}'.format(service.id, today_only),
                headers=[create_admin_authorization_header()],
            )

    assert resp.status_code == 200
    service_resp = resp.json['data']

    assert service_resp['id'] == str(service.id)
    assert 'statistics' in service_resp
    assert set(service_resp['statistics'].keys()) == {SMS_TYPE, EMAIL_TYPE, LETTER_TYPE}
    print('STATS:\n ', service_resp['statistics'])
    assert service_resp['statistics'][SMS_TYPE] == stats

    # Teardown
    notify_db_session.session.delete(notification_0)
    notify_db_session.session.delete(notification_1)
    notify_db_session.session.delete(ft_notification)
    notify_db_session.session.commit()


@pytest.mark.serial  # Cannot handle multiple workers
def test_get_services_with_detailed_flag(
    client,
    sample_api_key,
    sample_notification,
    sample_service,
    sample_template,
):
    service = sample_service()
    template = sample_template(service=service, user=service.users[0])
    normal_api_key = sample_api_key(service=service)
    test_api_key = sample_api_key(service=service, key_type=KEY_TYPE_TEST)

    notifications = [
        sample_notification(template=template, api_key=normal_api_key),
        sample_notification(template=template, api_key=normal_api_key),
        sample_notification(template=template, api_key=test_api_key),
    ]

    # Tests involving a check on all services cannot be done with multiple workers
    resp = client.get('/service?detailed=True', headers=[create_admin_authorization_header()])

    assert resp.status_code == 200
    data = resp.json['data']
    assert len(data) == 1
    assert data[0]['name'] == service.name
    assert data[0]['id'] == str(notifications[0].service_id)
    assert data[0]['statistics'] == {
        EMAIL_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
        SMS_TYPE: {'delivered': 0, 'failed': 0, 'requested': 3},
        LETTER_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
    }


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_services_with_detailed_flag_excluding_from_test_key(notify_api, sample_template):
    create_notification(sample_template, key_type=KEY_TYPE_NORMAL)
    create_notification(sample_template, key_type=KEY_TYPE_TEAM)
    create_notification(sample_template, key_type=KEY_TYPE_TEST)
    create_notification(sample_template, key_type=KEY_TYPE_TEST)
    create_notification(sample_template, key_type=KEY_TYPE_TEST)

    with notify_api.test_request_context(), notify_api.test_client() as client:
        resp = client.get(
            '/service?detailed=True&include_from_test_key=False',  # We do not use this functionality at all
            headers=[create_admin_authorization_header()],
        )

    assert resp.status_code == 200
    data = resp.json['data']
    assert len(data) == 1
    assert data[0]['statistics'] == {
        EMAIL_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
        SMS_TYPE: {'delivered': 0, 'failed': 0, 'requested': 2},
        LETTER_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
    }


def test_get_services_with_detailed_flag_accepts_date_range(client, mocker):
    mock_get_detailed_services = mocker.patch('app.service.rest.get_detailed_services', return_value={})
    resp = client.get(
        url_for('service.get_services', detailed=True, start_date='2001-01-01', end_date='2002-02-02'),  # Unused
        headers=[create_admin_authorization_header()],
    )

    mock_get_detailed_services.assert_called_once_with(
        start_date=date(2001, 1, 1), end_date=date(2002, 2, 2), only_active=ANY, include_from_test_key=ANY
    )
    assert resp.status_code == 200


@freeze_time('2002-02-02')
def test_get_services_with_detailed_flag_defaults_to_today(client, mocker):
    mock_get_detailed_services = mocker.patch('app.service.rest.get_detailed_services', return_value={})
    resp = client.get(url_for('service.get_services', detailed=True), headers=[create_admin_authorization_header()])

    mock_get_detailed_services.assert_called_once_with(
        end_date=date(2002, 2, 2), include_from_test_key=ANY, only_active=ANY, start_date=date(2002, 2, 2)
    )

    assert resp.status_code == 200


@pytest.mark.skip(reason='Do we utilize this?')
def test_get_detailed_services_groups_by_service(notify_db_session, sample_api_key, sample_service, sample_template):
    from app.service.rest import get_detailed_services

    service_0 = sample_service(service_name=f'get detailed services {uuid4()}', email_from='1')
    service_1 = sample_service(service_name=f'get detailed services {uuid4()}', email_from='2')
    api_key_0 = sample_api_key(service=service_0)
    api_key_1 = sample_api_key(service=service_1)

    service_0_template = sample_template(service=service_0)
    service_1_template = sample_template(service=service_1)

    notifications = [
        create_notification(service_0_template, api_key=api_key_0, status='created'),
        create_notification(service_1_template, api_key=api_key_1, status='created'),
        create_notification(service_0_template, api_key=api_key_0, status='delivered'),
        create_notification(service_0_template, api_key=api_key_0, status='created'),
    ]

    data = get_detailed_services(start_date=datetime.utcnow().date(), end_date=datetime.utcnow().date())
    data = sorted(data, key=lambda x: x['name'])

    assert len(data) == 2
    assert data[0]['id'] == str(service_0.id)
    assert data[0]['statistics'] == {
        EMAIL_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
        SMS_TYPE: {'delivered': 1, 'failed': 0, 'requested': 3},
        LETTER_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
    }
    assert data[1]['id'] == str(service_1.id)
    assert data[1]['statistics'] == {
        EMAIL_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
        SMS_TYPE: {'delivered': 0, 'failed': 0, 'requested': 1},
        LETTER_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
    }

    # Teardown
    for notification in notifications:
        notify_db_session.session.delete(notification)
    notify_db_session.session.commit()


@pytest.mark.skip(reason='Do we utilize this?')
def test_get_detailed_services_includes_services_with_no_notifications(
    notify_db_session, sample_api_key, sample_service, sample_template
):
    from app.service.rest import get_detailed_services

    service_0 = sample_service(service_name=f'get detailed services {uuid4()}', email_from='1')
    service_1 = sample_service(service_name=f'get detailed services {uuid4()}', email_from='2')
    api_key_0 = sample_api_key(service=service_0)

    service_0_template = sample_template(service=service_0)
    notification = create_notification(service_0_template, api_key=api_key_0)

    data = get_detailed_services(start_date=datetime.utcnow().date(), end_date=datetime.utcnow().date())
    data = sorted(data, key=lambda x: x['name'])

    assert len(data) == 2
    assert data[0]['id'] == str(service_0.id)
    assert data[0]['statistics'] == {
        EMAIL_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
        SMS_TYPE: {'delivered': 0, 'failed': 0, 'requested': 1},
        LETTER_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
    }
    assert data[1]['id'] == str(service_1.id)
    assert data[1]['statistics'] == {
        EMAIL_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
        SMS_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
        LETTER_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
    }

    # Teardown
    notify_db_session.session.delete(notification)
    notify_db_session.session.commit()


@pytest.mark.skip(reason='Do we utilize this?')
# This test assumes the local timezone is EST
def test_get_detailed_services_only_includes_todays_notifications(notify_db_session, sample_api_key, sample_template):
    from app.service.rest import get_detailed_services

    api_key = sample_api_key()
    template = sample_template(service=api_key.service)
    notifications = [
        create_notification(template, api_key=api_key, created_at=datetime(2015, 10, 10, 3, 59)),
        create_notification(template, api_key=api_key, created_at=datetime(2015, 10, 10, 4, 0)),
        create_notification(template, api_key=api_key, created_at=datetime(2015, 10, 10, 12, 0)),
        create_notification(template, api_key=api_key, created_at=datetime(2015, 10, 11, 3, 0)),
    ]

    with freeze_time('2015-10-10T12:00:00'):
        data = get_detailed_services(start_date=datetime.utcnow().date(), end_date=datetime.utcnow().date())
        data = sorted(data, key=lambda x: x['id'])

    assert len(data) == 1
    assert data[0]['statistics'] == {
        EMAIL_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
        SMS_TYPE: {'delivered': 0, 'failed': 0, 'requested': 3},
        LETTER_TYPE: {'delivered': 0, 'failed': 0, 'requested': 0},
    }

    # Teardown
    for notification in notifications:
        notify_db_session.session.delete(notification)
    notify_db_session.session.commit()


@pytest.mark.skip(reason='Do we utilize this?')
@pytest.mark.parametrize('start_date_delta, end_date_delta', [(2, 1), (3, 2), (1, 0)])
@freeze_time('2017-03-28T12:00:00')
def test_get_detailed_services_for_date_range(
    notify_db_session, sample_api_key, sample_template, start_date_delta, end_date_delta
):
    from app.service.rest import get_detailed_services

    api_key = sample_api_key()
    template = sample_template(service=api_key.service)
    create_ft_notification_status(
        utc_date=(datetime.utcnow() - timedelta(days=3)).date(), service=template.service, notification_type='sms'
    )
    create_ft_notification_status(
        utc_date=(datetime.utcnow() - timedelta(days=2)).date(), service=template.service, notification_type='sms'
    )
    create_ft_notification_status(
        utc_date=(datetime.utcnow() - timedelta(days=1)).date(), service=template.service, notification_type='sms'
    )

    notification = create_notification(template=template, created_at=datetime.utcnow(), status='delivered')

    start_date = (datetime.utcnow() - timedelta(days=start_date_delta)).date()
    end_date = (datetime.utcnow() - timedelta(days=end_date_delta)).date()

    data = get_detailed_services(
        only_active=False, include_from_test_key=True, start_date=start_date, end_date=end_date
    )

    assert len(data) == 1
    assert data[0]['statistics'][EMAIL_TYPE] == {'delivered': 0, 'failed': 0, 'requested': 0}
    assert data[0]['statistics'][SMS_TYPE] == {'delivered': 2, 'failed': 0, 'requested': 2}
    assert data[0]['statistics'][LETTER_TYPE] == {'delivered': 0, 'failed': 0, 'requested': 0}

    # Teardown
    notify_db_session.session.delete(notification)
    notify_db_session.session.commit()


def test_search_for_notification_by_to_field(client, notify_db_session, sample_template):
    sms_template = sample_template()
    email_template = sample_template(service=sms_template.service, template_type=EMAIL_TYPE)
    notification1 = create_notification(template=sms_template, to_field='+16502532222', normalised_to='+16502532222')
    notification2 = create_notification(
        template=email_template, to_field='jack@gmail.com', normalised_to='jack@gmail.com'
    )

    response = client.get(
        '/service/{}/notifications?to={}&template_type={}'.format(notification1.service_id, 'jack@gmail.com', 'email'),
        headers=[create_admin_authorization_header()],
    )
    notifications = response.get_json()['notifications']

    assert response.status_code == 200
    assert len(notifications) == 1
    assert str(notification2.id) == notifications[0]['id']

    # Teardown
    notify_db_session.session.delete(notification1)
    notify_db_session.session.delete(notification2)
    notify_db_session.session.commit()


def test_search_for_notification_by_to_field_return_empty_list_if_there_is_no_match(
    client, notify_db_session, sample_template
):
    sms_template = sample_template()
    email_template = sample_template(service=sms_template.service, template_type=EMAIL_TYPE)
    notification1 = create_notification(sms_template, to_field='+16502532222')
    notification2 = create_notification(email_template, to_field='jack@gmail.com')

    response = client.get(
        '/service/{}/notifications?to={}&template_type={}'.format(notification1.service_id, '+447700900800', 'sms'),
        headers=[create_admin_authorization_header()],
    )
    notifications = response.get_json()['notifications']

    assert response.status_code == 200
    assert len(notifications) == 0

    # Teardown
    notify_db_session.session.delete(notification1)
    notify_db_session.session.delete(notification2)
    notify_db_session.session.commit()


def test_search_for_notification_by_to_field_return_multiple_matches(client, notify_db_session, sample_template):
    sms_template = sample_template()
    email_template = sample_template(service=sms_template.service, template_type=EMAIL_TYPE)
    notification1 = create_notification(sms_template, to_field='+16502532222', normalised_to='+16502532222')
    notification2 = create_notification(sms_template, to_field=' +165 0253 2222 ', normalised_to='+16502532222')
    notification3 = create_notification(sms_template, to_field='+1 650 253 2222', normalised_to='+16502532222')
    notification4 = create_notification(email_template, to_field='jack@gmail.com', normalised_to='jack@gmail.com')

    response = client.get(
        '/service/{}/notifications?to={}&template_type={}'.format(notification1.service_id, '+16502532222', 'sms'),
        headers=[create_admin_authorization_header()],
    )
    notifications = response.get_json()['notifications']
    notification_ids = [notification['id'] for notification in notifications]

    assert response.status_code == 200
    assert len(notifications) == 3

    assert str(notification1.id) in notification_ids
    assert str(notification2.id) in notification_ids
    assert str(notification3.id) in notification_ids
    assert str(notification4.id) not in notification_ids

    # Teardown
    notify_db_session.session.delete(notification1)
    notify_db_session.session.delete(notification2)
    notify_db_session.session.delete(notification3)
    notify_db_session.session.delete(notification4)
    notify_db_session.session.commit()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_search_for_notification_by_to_field_return_400_for_letter_type(
    client, notify_db, notify_db_session, sample_service
):
    response = client.get(
        '/service/{}/notifications?to={}&template_type={}'.format(sample_service().id, 'A. Name', 'letter'),
        headers=[create_admin_authorization_header()],
    )
    response.status_code = 400
    error_message = response.get_json()
    assert error_message['message'] == 'Only email and SMS can use search by recipient'


def test_update_service_calls_send_notification_as_service_becomes_live(
    notify_db, notify_db_session, client, mocker, sample_service
):
    send_notification_mock = mocker.patch('app.service.rest.send_notification_to_service_users')

    restricted_service = sample_service(restricted=True)

    data = {'restricted': False}

    auth_header = create_admin_authorization_header()
    resp = client.post(
        'service/{}'.format(restricted_service.id),
        data=json.dumps(data),
        headers=[auth_header],
        content_type='application/json',
    )

    assert resp.status_code == 200
    send_notification_mock.assert_called_once_with(
        service_id=restricted_service.id,
        template_id='618185c6-3636-49cd-b7d2-6f6f5eb3bdde',
        personalisation={'service_name': restricted_service.name, 'message_limit': '1,000'},
        include_user_fields=['name'],
    )


def test_update_service_does_not_call_send_notification_for_live_service(sample_service, client, mocker):
    send_notification_mock = mocker.patch('app.service.rest.send_notification_to_service_users')

    data = {'restricted': True}

    auth_header = create_admin_authorization_header()
    resp = client.post(
        'service/{}'.format(sample_service().id),
        data=json.dumps(data),
        headers=[auth_header],
        content_type='application/json',
    )

    assert resp.status_code == 200
    assert not send_notification_mock.called


def test_update_service_does_not_call_send_notification_when_restricted_not_changed(sample_service, client, mocker):
    send_notification_mock = mocker.patch('app.service.rest.send_notification_to_service_users')

    data = {'name': 'Name of service'}

    auth_header = create_admin_authorization_header()
    resp = client.post(
        'service/{}'.format(sample_service().id),
        data=json.dumps(data),
        headers=[auth_header],
        content_type='application/json',
    )

    assert resp.status_code == 200
    assert not send_notification_mock.called


def test_search_for_notification_by_to_field_filters_by_status(client, notify_db_session, sample_template):
    template = sample_template()
    notification1 = create_notification(
        template, to_field='+16502532222', status='delivered', normalised_to='+16502532222'
    )
    notification2 = create_notification(
        template, to_field='+447700900855', status='sending', normalised_to='447700900855'
    )

    response = client.get(
        '/service/{}/notifications?to={}&status={}&template_type={}'.format(
            notification1.service_id, '+16502532222', 'delivered', 'sms'
        ),
        headers=[create_admin_authorization_header()],
    )
    notifications = response.get_json()['notifications']
    notification_ids = [notification['id'] for notification in notifications]

    assert response.status_code == 200
    assert len(notifications) == 1
    assert str(notification1.id) in notification_ids

    # Teardown
    notify_db_session.session.delete(notification1)
    notify_db_session.session.delete(notification2)
    notify_db_session.session.commit()


def test_search_for_notification_by_to_field_filters_by_statuses(client, notify_db_session, sample_template):
    template = sample_template()
    notification1 = create_notification(
        template, to_field='+16502532222', status='delivered', normalised_to='+16502532222'
    )
    notification2 = create_notification(
        template, to_field='+16502532222', status='sending', normalised_to='+16502532222'
    )

    response = client.get(
        '/service/{}/notifications?to={}&status={}&status={}&template_type={}'.format(
            notification1.service_id, '+16502532222', 'delivered', 'sending', 'sms'
        ),
        headers=[create_admin_authorization_header()],
    )
    notifications = response.get_json()['notifications']
    notification_ids = [notification['id'] for notification in notifications]

    assert response.status_code == 200
    assert len(notifications) == 2
    assert str(notification1.id) in notification_ids
    assert str(notification2.id) in notification_ids

    # Teardown
    notify_db_session.session.delete(notification1)
    notify_db_session.session.delete(notification2)
    notify_db_session.session.commit()


def test_search_for_notification_by_to_field_returns_content(
    client,
    notify_db_session,
    sample_template,
):
    template = sample_template(content='Hello (( Name))\nYour thing is due soon')

    notification = create_notification(
        template,
        to_field='+16502532222',
        personalisation={'name': 'Foo'},
        normalised_to='+16502532222',
    )

    response = client.get(
        '/service/{}/notifications?to={}&template_type={}'.format(template.service_id, '+16502532222', 'sms'),
        headers=[create_admin_authorization_header()],
    )
    notifications = response.get_json()['notifications']
    assert response.status_code == 200
    assert len(notifications) == 1

    assert notifications[0]['id'] == str(notification.id)
    assert notifications[0]['to'] == '+16502532222'
    assert notifications[0]['template']['content'] == 'Hello (( Name))\nYour thing is due soon'

    # Teardown
    notify_db_session.session.delete(notification)
    notify_db_session.session.commit()


def test_send_one_off_notification(notify_db_session, sample_service, admin_request, mocker, sample_template):
    service = sample_service()
    template = sample_template(service=service)
    mocker.patch('app.service.send_notification.send_notification_to_queue')

    response = admin_request.post(
        'service.create_one_off_notification',
        service_id=service.id,
        _data={'template_id': str(template.id), 'to': '+16502532222', 'created_by': str(service.created_by_id)},
        _expected_status=201,
    )

    noti = notify_db_session.session.get(Notification, response['id'])
    assert response['id'] == str(noti.id)

    # Teardown
    notify_db_session.session.delete(noti)
    notify_db_session.session.commit()


def test_get_notification_for_service_includes_template_redacted(
    admin_request, notify_db_session, sample_notification, sample_template
):
    template = sample_template()
    notification = sample_notification(template=template)
    resp = admin_request.get(
        'service.get_notification_for_service', service_id=notification.service_id, notification_id=notification.id
    )

    assert resp['id'] == str(notification.id)
    assert resp['template']['redact_personalisation'] is False

    # Teardown
    notify_db_session.session.delete(notification)
    notify_db_session.session.commit()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_notification_for_service_includes_precompiled_letter(admin_request, sample_notification):
    notification = sample_notification()
    resp = admin_request.get(
        'service.get_notification_for_service', service_id=notification.service_id, notification_id=notification.id
    )

    assert resp['id'] == str(notification.id)
    assert resp['template']['is_precompiled_letter'] is False


def test_get_all_notifications_for_service_includes_template_redacted(
    admin_request, notify_db_session, sample_service, sample_template
):
    service = sample_service()
    normal_template = sample_template(service=service)

    redacted_template = sample_template(service=service)
    dao_redact_template(redacted_template, service.created_by_id)

    with freeze_time('2000-01-01'):
        redacted_noti = create_notification(redacted_template)
    with freeze_time('2000-01-02'):
        normal_noti = create_notification(normal_template)

    resp = admin_request.get('service.get_all_notifications_for_service', service_id=service.id)

    assert resp['notifications'][0]['id'] == str(normal_noti.id)
    assert resp['notifications'][0]['template']['redact_personalisation'] is False

    assert resp['notifications'][1]['id'] == str(redacted_noti.id)
    assert resp['notifications'][1]['template']['redact_personalisation'] is True

    # Teardown
    notify_db_session.session.delete(redacted_noti)
    notify_db_session.session.delete(normal_noti)
    notify_db_session.session.commit()


# Precompiled letters are not something we do or plan to do
@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_all_notifications_for_service_includes_template_hidden(
    admin_request, notify_db_session, sample_service, sample_template
):
    service = sample_service()
    letter_template = sample_template(service=service, template_type=LETTER_TYPE)
    precompiled_template = sample_template(
        service=service,
        template_type=LETTER_TYPE,
        name=f'Pre-compiled PDF{uuid4()}',
        subject='Pre-compiled PDF',
        hidden=True,
    )

    with freeze_time('2000-01-01'):
        letter_noti = create_notification(letter_template)
    with freeze_time('2000-01-02'):
        precompiled_noti = create_notification(precompiled_template)

    resp = admin_request.get('service.get_all_notifications_for_service', service_id=service.id)
    print(resp['notifications'][0])
    print()
    print(resp['notifications'][1])
    assert resp['notifications'][0]['id'] == str(precompiled_noti.id)
    assert resp['notifications'][0]['template']['is_precompiled_letter'] is True

    assert resp['notifications'][1]['id'] == str(letter_noti.id)
    assert resp['notifications'][1]['template']['is_precompiled_letter'] is False

    # Teardown
    notify_db_session.session.delete(letter_noti)
    notify_db_session.session.delete(precompiled_noti)
    notify_db_session.session.commit()


def test_search_for_notification_by_to_field_returns_personlisation(
    client,
    notify_db_session,
    sample_template,
):
    template = sample_template(content='Hello (( Name))\nYour thing is due soon')
    notification = create_notification(
        template,
        to_field='+16502532222',
        personalisation={'name': 'Foo'},
        normalised_to='+16502532222',
    )

    response = client.get(
        '/service/{}/notifications?to={}&template_type={}'.format(template.service_id, '+16502532222', 'sms'),
        headers=[create_admin_authorization_header()],
    )
    notifications = response.get_json()['notifications']

    assert response.status_code == 200
    assert len(notifications) == 1
    assert 'personalisation' in notifications[0].keys()
    assert notifications[0]['personalisation']['name'] == 'Foo'

    # Teardown
    notify_db_session.session.delete(notification)
    notify_db_session.session.commit()


def test_search_for_notification_by_to_field_returns_notifications_by_type(
    client,
    notify_db_session,
    sample_template,
):
    sms_notification = create_notification(sample_template(), to_field='+16502532222', normalised_to='+16502532222')
    email_notification = create_notification(
        sample_template(template_type=EMAIL_TYPE), to_field='44770@gamil.com', normalised_to='44770@gamil.com'
    )

    response = client.get(
        '/service/{}/notifications?to={}&template_type={}'.format(sms_notification.service_id, '650', 'sms'),
        headers=[create_admin_authorization_header()],
    )
    notifications = response.get_json()['notifications']

    assert response.status_code == 200
    assert len(notifications) == 1
    assert notifications[0]['id'] == str(sms_notification.id)

    # Teardown
    notify_db_session.session.delete(sms_notification)
    notify_db_session.session.delete(email_notification)
    notify_db_session.session.commit()


def test_is_service_name_unique_returns_200_if_unique(admin_request, notify_db, notify_db_session, sample_service):
    service = sample_service(service_name='unique', email_from='unique')

    response = admin_request.get(
        'service.is_service_name_unique',
        _expected_status=200,
        service_id=service.id,
        name='something',
        email_from='something',
    )

    assert response == {'result': True}


@pytest.mark.serial  # Would have to break into multiple tests or many if/else checks in the test if ran w/many workers
@pytest.mark.parametrize(
    'name, email_from',
    [
        ('UNIQUE', 'unique'),
        ('Unique.', 'unique'),
        ('**uniQUE**', 'unique'),
    ],
)
def test_is_service_name_unique_returns_200_with_name_capitalized_or_punctuation_added(
    admin_request,
    name,
    email_from,
    sample_service,
):
    """
    The variations tested in the parameterization do not play nice with a random UUID, so this should be ran with a
    specific service name that tests various similar naming techniques.
    """
    service = sample_service(service_name='unique', email_from='unique')

    response = admin_request.get(
        'service.is_service_name_unique', _expected_status=200, service_id=service.id, name=name, email_from=email_from
    )

    assert response == {'result': True}


@pytest.mark.parametrize('name, email_from', [('existing name', 'email.from'), ('name', 'existing.name')])
def test_is_service_name_unique_returns_200_and_false_if_name_or_email_from_exist_for_a_different_service(
    admin_request,
    notify_db,
    notify_db_session,
    name,
    email_from,
    sample_service,
):
    sample_service(service_name='existing name', email_from='existing.name')
    different_service_id = '111aa111-2222-bbbb-aaaa-111111111111'

    response = admin_request.get(
        'service.is_service_name_unique',
        _expected_status=200,
        service_id=different_service_id,
        name=name,
        email_from=email_from,
    )

    assert response == {'result': False}


def test_is_service_name_unique_returns_200_and_false_if_name_exists_for_the_same_service(
    admin_request,
    sample_service,
):
    service_name = f'unique_name{uuid4()}'
    service = sample_service(service_name=service_name, email_from=service_name)

    response = admin_request.get(
        'service.is_service_name_unique',
        _expected_status=200,
        service_id=service.id,
        name=service_name,
        email_from='unique2',
    )

    assert response == {'result': False}


def test_is_service_name_unique_returns_400_when_name_does_not_exist(admin_request):
    response = admin_request.get('service.is_service_name_unique', _expected_status=400)

    assert response['message'][0]['service_id'] == ["Can't be empty"]
    assert response['message'][1]['name'] == ["Can't be empty"]
    assert response['message'][2]['email_from'] == ["Can't be empty"]


def test_get_email_reply_to_addresses_when_there_are_no_reply_to_email_addresses(client, sample_service):
    service = sample_service(email_address=None)
    response = client.get(f'/service/{service.id}/email-reply-to', headers=[create_admin_authorization_header()])

    assert response.status_code == 200
    assert response.get_json() == []


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_email_reply_to_addresses_with_one_email_address(
    client,
    notify_db_session,
    sample_service,
):
    service = sample_service()
    reply_to_email = create_reply_to_email(service, 'test@mail.com')

    response = client.get(
        '/service/{}/email-reply-to'.format(service.id), headers=[create_admin_authorization_header()]
    )
    json_response = response.get_json()

    assert len(json_response) == 1
    assert json_response[0]['email_address'] == 'test@mail.com'
    assert json_response[0]['is_default']
    assert json_response[0]['created_at']
    assert not json_response[0]['updated_at']
    assert response.status_code == 200

    # Teardown
    notify_db_session.session.delete(reply_to_email)
    notify_db_session.session.commit()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_email_reply_to_addresses_with_multiple_email_addresses(
    client, notify_db, notify_db_session, sample_service
):
    service = sample_service()
    reply_to_a = create_reply_to_email(service, 'test_a@mail.com')
    reply_to_b = create_reply_to_email(service, 'test_b@mail.com', False)

    response = client.get(
        '/service/{}/email-reply-to'.format(service.id), headers=[create_admin_authorization_header()]
    )
    json_response = response.get_json()

    assert len(json_response) == 2
    assert response.status_code == 200

    assert json_response[0]['id'] == str(reply_to_a.id)
    assert json_response[0]['service_id'] == str(reply_to_a.service_id)
    assert json_response[0]['email_address'] == 'test_a@mail.com'
    assert json_response[0]['is_default']
    assert json_response[0]['created_at']
    assert not json_response[0]['updated_at']

    assert json_response[1]['id'] == str(reply_to_b.id)
    assert json_response[1]['service_id'] == str(reply_to_b.service_id)
    assert json_response[1]['email_address'] == 'test_b@mail.com'
    assert not json_response[1]['is_default']
    assert json_response[1]['created_at']
    assert not json_response[1]['updated_at']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_verify_reply_to_email_address_should_send_verification_email(
    admin_request, notify_db, notify_db_session, mocker, verify_reply_to_address_email_template, sample_service
):
    service = sample_service()
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    data = {'email': 'reply-here@example.va.gov'}
    notify_service = verify_reply_to_address_email_template.service
    response = admin_request.post(
        'service.verify_reply_to_email_address', service_id=service.id, _data=data, _expected_status=201
    )

    notification = Notification.query.first()
    assert notification.template_id == verify_reply_to_address_email_template.id
    assert response['data'] == {'id': str(notification.id)}
    assert notification.reply_to_text == notify_service.get_default_reply_to_email_address()

    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == str(notification.id)
    assert result_queue['queue'] == 'notify-internal-tasks'
    mocked.assert_called_once()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_verify_reply_to_email_address_doesnt_allow_duplicates(
    admin_request, notify_db, notify_db_session, mocker, sample_service
):
    data = {'email': 'reply-here@example.va.gov'}
    service = sample_service()
    create_reply_to_email(service, 'reply-here@example.va.gov')
    response = admin_request.post(
        'service.verify_reply_to_email_address', service_id=service.id, _data=data, _expected_status=400
    )
    assert response['message'] == 'Your service already uses ‘reply-here@example.va.gov’ as an email reply-to address.'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_service_reply_to_email_address(admin_request, notify_db_session, sample_service):
    service = sample_service()
    data = {'email_address': 'new@reply.com', 'is_default': True}
    response = admin_request.post(
        'service.add_service_reply_to_email_address', service_id=service.id, _data=data, _expected_status=201
    )

    stmt = select(ServiceEmailReplyTo).where(ServiceEmailReplyTo.service_id == service.id)
    results = notify_db_session.session.scalars(stmt).all()
    assert len(results) == 1
    assert response['data'] == results[0].serialize()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_service_reply_to_email_address_doesnt_allow_duplicates(
    admin_request, notify_db, notify_db_session, mocker, sample_service
):
    data = {'email_address': 'reply-here@example.va.gov', 'is_default': True}
    service = sample_service()
    create_reply_to_email(service, 'reply-here@example.va.gov')
    response = admin_request.post(
        'service.add_service_reply_to_email_address', service_id=service.id, _data=data, _expected_status=400
    )
    assert response['message'] == 'Your service already uses ‘reply-here@example.va.gov’ as an email reply-to address.'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_service_reply_to_email_address_can_add_multiple_addresses(admin_request, sample_service):
    data = {'email_address': 'first@reply.com', 'is_default': True}
    admin_request.post(
        'service.add_service_reply_to_email_address', service_id=sample_service.id, _data=data, _expected_status=201
    )
    second = {'email_address': 'second@reply.com', 'is_default': True}
    response = admin_request.post(
        'service.add_service_reply_to_email_address', service_id=sample_service.id, _data=second, _expected_status=201
    )
    results = ServiceEmailReplyTo.query.all()
    assert len(results) == 2
    default = [x for x in results if x.is_default]
    assert response['data'] == default[0].serialize()
    first_reply_to_not_default = [x for x in results if not x.is_default]
    assert first_reply_to_not_default[0].email_address == 'first@reply.com'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_add_service_reply_to_email_address_raise_exception_if_no_default(admin_request, sample_service):
    data = {'email_address': 'first@reply.com', 'is_default': False}
    response = admin_request.post(
        'service.add_service_reply_to_email_address', service_id=sample_service.id, _data=data, _expected_status=400
    )
    assert response['message'] == 'You must have at least one reply to email address as the default.'


def test_add_service_reply_to_email_address_404s_when_invalid_service_id(admin_request, notify_db, notify_db_session):
    response = admin_request.post(
        'service.add_service_reply_to_email_address', service_id=uuid.uuid4(), _data={}, _expected_status=404
    )

    assert response['result'] == 'error'
    assert response['message'] == 'No result found'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_service_reply_to_email_address(admin_request, sample_service):
    original_reply_to = create_reply_to_email(service=sample_service, email_address='some@email.com')
    data = {'email_address': 'changed@reply.com', 'is_default': True}
    response = admin_request.post(
        'service.update_service_reply_to_email_address',
        service_id=sample_service.id,
        reply_to_email_id=original_reply_to.id,
        _data=data,
        _expected_status=200,
    )

    results = ServiceEmailReplyTo.query.all()
    assert len(results) == 1
    assert response['data'] == results[0].serialize()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_service_reply_to_email_address_returns_400_when_no_default(admin_request, sample_service):
    original_reply_to = create_reply_to_email(service=sample_service, email_address='some@email.com')
    data = {'email_address': 'changed@reply.com', 'is_default': False}
    response = admin_request.post(
        'service.update_service_reply_to_email_address',
        service_id=sample_service.id,
        reply_to_email_id=original_reply_to.id,
        _data=data,
        _expected_status=400,
    )

    assert response['message'] == 'You must have at least one reply to email address as the default.'


def test_update_service_reply_to_email_address_404s_when_invalid_service_id(
    admin_request, notify_db, notify_db_session
):
    response = admin_request.post(
        'service.update_service_reply_to_email_address',
        service_id=uuid.uuid4(),
        reply_to_email_id=uuid.uuid4(),
        _data={},
        _expected_status=404,
    )

    assert response['result'] == 'error'
    assert response['message'] == 'No result found'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_delete_service_reply_to_email_address_archives_an_email_reply_to(
    sample_service, admin_request, notify_db_session
):
    create_reply_to_email(service=sample_service, email_address='some@email.com')
    reply_to = create_reply_to_email(service=sample_service, email_address='some@email.com', is_default=False)

    admin_request.post(
        'service.delete_service_reply_to_email_address',
        service_id=sample_service.id,
        reply_to_email_id=reply_to.id,
    )
    assert reply_to.archived is True


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_delete_service_reply_to_email_address_returns_400_if_archiving_default_reply_to(
    admin_request, notify_db_session, sample_service
):
    reply_to = create_reply_to_email(service=sample_service, email_address='some@email.com')

    response = admin_request.post(
        'service.delete_service_reply_to_email_address',
        service_id=sample_service.id,
        reply_to_email_id=reply_to.id,
        _expected_status=400,
    )

    assert response == {'message': 'You cannot delete a default email reply to address', 'result': 'error'}
    assert reply_to.archived is False


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_email_reply_to_address(client, notify_db, notify_db_session, sample_service):
    service = sample_service()
    reply_to = create_reply_to_email(service, 'test_a@mail.com')

    response = client.get(
        '/service/{}/email-reply-to/{}'.format(service.id, reply_to.id),
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
    )

    assert response.status_code == 200
    assert response.get_json() == reply_to.serialize()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_organisation_for_service_id(admin_request, sample_service, sample_organisation):
    dao_add_service_to_organisation(sample_service, sample_organisation.id)
    response = admin_request.get('service.get_organisation_for_service', service_id=sample_service.id)
    assert response == sample_organisation.serialize()


def test_get_organisation_for_service_id_return_empty_dict_if_service_not_in_organisation(admin_request, fake_uuid):
    response = admin_request.get('service.get_organisation_for_service', service_id=fake_uuid)
    assert response == {}


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_cancel_notification_for_service_raises_invalid_request_when_notification_is_not_found(
    admin_request,
    sample_service,
    fake_uuid,
):
    response = admin_request.post(
        'service.cancel_notification_for_service',
        service_id=sample_service.id,
        notification_id=fake_uuid,
        _expected_status=404,
    )
    assert response['message'] == 'Notification not found'
    assert response['result'] == 'error'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_cancel_notification_for_service_raises_invalid_request_when_notification_is_not_a_letter(
    admin_request,
    sample_notification,
):
    response = admin_request.post(
        'service.cancel_notification_for_service',
        service_id=sample_notification.service_id,
        notification_id=sample_notification.id,
        _expected_status=400,
    )
    assert response['message'] == 'Notification cannot be cancelled - only letters can be cancelled'
    assert response['result'] == 'error'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'notification_status',
    [
        'cancelled',
        'sending',
        'sent',
        'delivered',
        'pending',
        'failed',
        'technical-failure',
        'temporary-failure',
        'permanent-failure',
        'validation-failed',
        'virus-scan-failed',
        'returned-letter',
    ],
)
@freeze_time('2018-07-07 12:00:00')
def test_cancel_notification_for_service_raises_invalid_request_when_letter_is_in_wrong_state_to_be_cancelled(
    admin_request,
    sample_letter_notification,
    notification_status,
):
    sample_letter_notification.status = notification_status

    response = admin_request.post(
        'service.cancel_notification_for_service',
        service_id=sample_letter_notification.service_id,
        notification_id=sample_letter_notification.id,
        _expected_status=400,
    )
    assert response['message'] == 'It’s too late to cancel this letter. Printing started today at 5.30pm'
    assert response['result'] == 'error'


@pytest.mark.parametrize('notification_status', ['created', 'pending-virus-check'])
@freeze_time('2018-07-07 16:00:00')
@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_cancel_notification_for_service_updates_letter_if_letter_is_in_cancellable_state(
    admin_request,
    sample_letter_notification,
    notification_status,
):
    sample_letter_notification.status = notification_status
    sample_letter_notification.created_at = datetime.now()

    response = admin_request.post(
        'service.cancel_notification_for_service',
        service_id=sample_letter_notification.service_id,
        notification_id=sample_letter_notification.id,
    )
    assert response['status'] == 'cancelled'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@freeze_time('2017-12-12 17:30:00')
def test_cancel_notification_for_service_raises_error_if_its_too_late_to_cancel(
    admin_request,
    sample_letter_notification,
):
    sample_letter_notification.created_at = datetime(2017, 12, 11, 17, 0)

    response = admin_request.post(
        'service.cancel_notification_for_service',
        service_id=sample_letter_notification.service_id,
        notification_id=sample_letter_notification.id,
        _expected_status=400,
    )
    assert response['message'] == 'It’s too late to cancel this letter. Printing started on 11 December at 5.30pm'
    assert response['result'] == 'error'


@freeze_time('2018-7-7 16:00:00')
@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_cancel_notification_for_service_updates_letter_if_still_time_to_cancel(
    admin_request,
    sample_letter_notification,
):
    sample_letter_notification.created_at = datetime(2018, 7, 7, 10, 0)

    response = admin_request.post(
        'service.cancel_notification_for_service',
        service_id=sample_letter_notification.service_id,
        notification_id=sample_letter_notification.id,
    )
    assert response['status'] == 'cancelled'


def test_get_monthly_notification_data_by_service(mocker, admin_request):
    dao_mock = mocker.patch(
        'app.service.rest.fact_notification_status_dao.fetch_monthly_notification_statuses_per_service', return_value=[]
    )

    start_date = '2019-01-01'
    end_date = '2019-06-17'

    response = admin_request.get(
        'service.get_monthly_notification_data_by_service', start_date=start_date, end_date=end_date
    )

    dao_mock.assert_called_once_with(start_date, end_date)
    assert response == []


def test_create_smtp_relay_for_service_if_it_already_has_one(
    client,
    sample_service,
):
    service = sample_service(smtp_user='foo')

    resp = client.post('/service/{}/smtp'.format(service.id), headers=[create_admin_authorization_header()])

    assert resp.status_code == 500


def test_create_smtp_relay_for_service(
    mocker,
    client,
    sample_service,
):
    service = sample_service(smtp_user=None)

    credentials = {
        'iam': 'iam_username',
        'domain': 'domain',
        'name': 'smtp.relay',
        'port': '465',
        'tls': 'Yes',
        'username': 'foo',
        'password': 'bar',
    }

    add_mock = mocker.patch('app.service.rest.smtp_add', return_value=credentials)

    resp = client.post('/service/{}/smtp'.format(service.id), headers=[create_admin_authorization_header()])

    add_mock.assert_called_once()
    assert resp.status_code == 201
    json_resp = resp.get_json()
    assert json_resp == credentials


def test_get_smtp_relay_for_service(
    mocker,
    client,
    sample_service,
):
    service = sample_service(smtp_user='FOO-BAR')

    username_mock = mocker.patch('app.service.rest.smtp_get_user_key', return_value='bar')

    credentials = {
        'domain': 'FOO',
        'name': 'email-smtp.us-east-1.amazonaws.com',
        'port': '465',
        'tls': 'Yes',
        'username': 'bar',
    }

    resp = client.get('/service/{}/smtp'.format(service.id), headers=[create_admin_authorization_header()])

    username_mock.assert_called_once()
    assert resp.status_code == 200
    json_resp = resp.get_json()
    assert json_resp == credentials


def test_get_smtp_relay_for_service_returns_empty_if_none(
    mocker,
    client,
    sample_service,
):
    service = sample_service(smtp_user=None)

    resp = client.get('/service/{}/smtp'.format(service.id), headers=[create_admin_authorization_header()])

    assert resp.status_code == 200
    json_resp = resp.get_json()
    assert json_resp == {}


def test_delete_smtp_relay_for_service_returns_500_if_none(
    mocker,
    client,
    sample_service,
):
    service = sample_service(smtp_user=None)

    resp = client.delete('/service/{}/smtp'.format(service.id), headers=[create_admin_authorization_header()])

    assert resp.status_code == 500


def test_delete_smtp_relay_for_service_returns_201_if_success(
    mocker,
    client,
    sample_service,
):
    service = sample_service(smtp_user=f'foo{uuid4()}')

    delete_mock = mocker.patch('app.service.rest.smtp_remove')

    resp = client.delete('/service/{}/smtp'.format(service.id), headers=[create_admin_authorization_header()])

    delete_mock.assert_called_once()
    assert resp.status_code == 201
