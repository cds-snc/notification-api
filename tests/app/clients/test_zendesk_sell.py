import json
import pytest
import requests_mock

from flask import Flask
from pytest_mock import MockFixture
from typing import Dict, Union, Optional

from app.clients.zendesk_sell import ZenDeskSell
from app.models import Service
from app.user.contact_request import ContactRequest


def test_create_lead(notify_api: Flask):
    def match_json(request):
        expected = {
            'data': {
                'last_name': 'User',
                'first_name': 'Test',
                'organization_name': '',
                'email': 'test@email.com',
                'description': 'Program: \n: ',
                'tags': ["", "en"],
                'status': 'New',
                'source_id': 2085874,
                "owner_id": ZenDeskSell.OWNER_ID,
                'custom_fields': {
                    'Product': ['Notify'],
                    'Intended recipients': 'No value'
                }
            }
        }

        json_matches = request.json() == expected
        basic_auth_header = request.headers.get('Authorization') == 'Bearer zendesksell-api-key'

        return json_matches and basic_auth_header

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            url='https://zendesksell-test.com/v2/leads/upsert?email=test@email.com',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=201
        )

        with notify_api.app_context():
            data = {'email_address': "test@email.com", 'name': 'Test User'}
            response = ZenDeskSell().upsert_lead(ContactRequest(**data))
            assert response == 201


def test_create_lead_missing_name(notify_api: Flask):

    # Name field is a requirement for the zendesk sell API interface
    with notify_api.app_context():
        with pytest.raises(AssertionError):
            ZenDeskSell().upsert_lead(ContactRequest(**{'email_address': 'test@email.com'}))


def generate_contact_url(existing_contact_id: Optional[str], service: Service) -> str:
    if existing_contact_id:
        return f'https://zendesksell-test.com/v2/contacts/{existing_contact_id}'
    else:
        return f'https://zendesksell-test.com/v2/contacts/upsert?' \
               f'custom_fields[notify_user_id]={str(service.users[0].id)}'


def contact_http_method(existing_contact_id: Optional[str]):
    return 'PUT' if existing_contact_id else 'POST'


@pytest.mark.parametrize('existing_contact_id,created_at,updated_at,expected_created', [
    (None, '2021-03-24T14:49:38Z', '2021-03-24T14:49:38Z', True),
    (None, '2021-03-24T14:49:38Z', '2021-04-24T14:49:38Z', False),
    ('1', '2021-03-24T14:49:38Z', '2021-04-24T14:49:38Z', False)
])
def test_create_or_upsert_contact(
        existing_contact_id: Optional[str],
        created_at: str,
        updated_at: str,
        expected_created: bool,
        notify_api: Flask,
        sample_service: Service
):

    def match_json(request):
        expected = {
            'data': {
                'last_name': 'User',
                'first_name': 'Test',
                'email': 'notify@digital.cabinet-office.gov.uk',
                'mobile': '+16502532222',
                'owner_id': ZenDeskSell.OWNER_ID,
                'custom_fields': {
                    'notify_user_id': str(sample_service.users[0].id)
                }
            }
        }

        json_matches = request.json() == expected
        basic_auth_header = request.headers.get('Authorization') == 'Bearer zendesksell-api-key'

        return json_matches and basic_auth_header

    with requests_mock.mock() as rmock:
        expected_contact_id = existing_contact_id or '123456789'
        resp_data = {
            'data': {
                'id': expected_contact_id,
                'created_at': created_at,
                'updated_at': updated_at
            }
        }
        rmock.request(
            contact_http_method(existing_contact_id),
            url=generate_contact_url(existing_contact_id, sample_service),
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=200,
            text=json.dumps(resp_data)
        )
        with notify_api.app_context():
            contact_id, is_created = ZenDeskSell().upsert_contact(sample_service.users[0], existing_contact_id)
            assert expected_contact_id == contact_id
            assert is_created == expected_created


@pytest.mark.parametrize('existing_contact_id,expected_resp_data', [
    (None, {'blank': 'blank'}),
    (None, {'data': {'created_at': '2021-02-24T14:49:38Z', 'updated_at': '2021-03-24T14:49:38Z'}}),
    (None, {'data': {'id': '123456789', 'created_at': '2021-02-24T14:49:38Z'}}),
    (None, {'data': {'id': '123456789', 'updated_at': '2021-02-24T14:49:38Z'}}),
    (1, {'blank': 'blank'}),
    (1, {'data': {'created_at': '2021-02-24T14:49:38Z', 'updated_at': '2021-03-24T14:49:38Z'}}),
    (1, {'data': {'id': '123456789', 'created_at': '2021-02-24T14:49:38Z'}}),
    (1, {'data': {'id': '123456789', 'updated_at': '2021-02-24T14:49:38Z'}})
])
def test_create_contact_invalid_response(notify_api: Flask,
                                         sample_service: Service,
                                         existing_contact_id: Optional[str],
                                         expected_resp_data: Dict[str, Dict[str, Union[int, str]]]):
    def match_json(request):
        expected = {
            'data': {
                'last_name': 'User',
                'first_name': 'Test',
                'email': 'notify@digital.cabinet-office.gov.uk',
                'mobile': '+16502532222',
                'owner_id': ZenDeskSell.OWNER_ID,
                'custom_fields': {
                    'notify_user_id': str(sample_service.users[0].id)
                }
            }
        }

        json_matches = request.json() == expected
        basic_auth_header = request.headers.get('Authorization') == 'Bearer zendesksell-api-key'

        return json_matches and basic_auth_header

    with requests_mock.mock() as rmock:
        rmock.request(
            contact_http_method(existing_contact_id),
            url=generate_contact_url(existing_contact_id, sample_service),
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=200,
            text=json.dumps(expected_resp_data)

        )
        with notify_api.app_context():
            contact_id, _ = ZenDeskSell().upsert_contact(sample_service.users[0], existing_contact_id)
            assert not contact_id


def test_convert_lead_to_contact(notify_api: Flask, sample_service: Service):
    lead_id = '123456789'

    def match_json(request):
        expected = {
            'data': {
                'lead_id': lead_id,
                'owner_id': ZenDeskSell.OWNER_ID,
                'create_deal': False
            }
        }

        json_matches = request.json() == expected
        basic_auth_header = request.headers.get('Authorization') == 'Bearer zendesksell-api-key'

        return json_matches and basic_auth_header

    with requests_mock.mock() as rmock:
        expected_contact_id = '1234567890'
        rmock.request(
            "GET",
            url=f'https://zendesksell-test.com/v2/leads?email={sample_service.users[0].email_address}',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            status_code=200,
            text=json.dumps({'items': [{'data': {'id': lead_id}}]})
        )
        rmock.request(
            "POST",
            url='https://zendesksell-test.com/v2/lead_conversions',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=200,
            text=json.dumps({'data': {'individual_id': expected_contact_id}})
        )

        with notify_api.app_context():
            contact_id = ZenDeskSell().convert_lead_to_contact(sample_service.users[0])
            assert contact_id == expected_contact_id


def test_convert_lead_to_contact_search_fails(notify_api: Flask, sample_service: Service, mocker: MockFixture):

    with notify_api.app_context():
        search_lead_id_mock = mocker.patch('app.user.rest.ZenDeskSell.search_lead_id', return_value=None)
        contact_id = ZenDeskSell().convert_lead_to_contact(sample_service.users[0])
        search_lead_id_mock.assert_called_once_with(sample_service.users[0])
        assert not contact_id


def test_delete_contact(notify_api: Flask):
    def match_header(request):
        return request.headers.get('Authorization') == 'Bearer zendesksell-api-key'

    with requests_mock.mock() as rmock:
        contact_id = '123456789'
        rmock.request(
            "DELETE",
            url=f'https://zendesksell-test.com/v2/contacts/{contact_id}',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_header,
            status_code=200
        )

        with notify_api.app_context():
            # as long as it doesn't throw we are OK as this is a best effort method
            ZenDeskSell().delete_contact(contact_id)


def test_create_deal(notify_api: Flask, sample_service: Service):
    def match_json(request):
        expected = {
            'data': {
                'contact_id': '123456789',
                'name': 'Sample service',
                'stage_id': 123456789,
                'owner_id': ZenDeskSell.OWNER_ID,
                'custom_fields': {
                    'notify_service_id': str(sample_service.id)
                }
            }
        }

        json_matches = request.json() == expected
        basic_auth_header = request.headers.get('Authorization') == 'Bearer zendesksell-api-key'

        return json_matches and basic_auth_header

    with requests_mock.mock() as rmock:
        contact_id = '123456789'
        expected_deal_id = '987654321'
        resp_data = {'data': {'id': expected_deal_id, 'contact_id': contact_id}}
        rmock.request(
            "POST",
            url=f'https://zendesksell-test.com/v2/deals/upsert?contact_id={contact_id}'
                f'&custom_fields%5Bnotify_service_id%5D={str(sample_service.id)}',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=200,
            text=json.dumps(resp_data)
        )

        with notify_api.app_context():
            deal_id = ZenDeskSell().upsert_deal(contact_id, sample_service, 123456789)
            assert expected_deal_id == deal_id


@pytest.mark.parametrize('expected_resp_data', [
    {'blank': 'blank'},
    {'data': {'blank': 'blank'}},
])
def test_create_deal_invalid_response(notify_api: Flask,
                                      sample_service: Service,
                                      expected_resp_data: Dict[str, Dict[str, Union[int, str]]]):
    def match_json(request):
        expected = {
            'data': {
                'contact_id': '123456789',
                'name': 'Sample service',
                'stage_id': 123456789,
                'owner_id': ZenDeskSell.OWNER_ID,
                'custom_fields': {
                    'notify_service_id': str(sample_service.id)
                }
            }
        }

        json_matches = request.json() == expected
        basic_auth_header = request.headers.get('Authorization') == 'Bearer zendesksell-api-key'

        return json_matches and basic_auth_header

    with requests_mock.mock() as rmock:
        contact_id = '123456789'
        rmock.request(
            "POST",
            url=f'https://zendesksell-test.com/v2/deals/upsert?contact_id={contact_id}'
                f'&custom_fields[notify_service_id]={str(sample_service.id)}',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=200,
            text=json.dumps(expected_resp_data)
        )

        with notify_api.app_context():
            deal_id = ZenDeskSell().upsert_deal(contact_id, sample_service, 123456789)
            assert not deal_id


def test_create_note(notify_api: Flask):
    resource_id = '1'

    def match_json(request):
        expected = {
            'data': {
                'resource_type': 'deal',
                'resource_id': resource_id,
                'content': '\n'.join(['Live Notes',
                                      'service_name just requested to go live.',
                                      '',
                                      '- Department/org: department_org_name',
                                      '- Intended recipients: intended_recipients',
                                      '- Purpose: main_use_case',
                                      '- Notification types: notification_types',
                                      '- Expected monthly volume: expected_volume',
                                      '---',
                                      'service_url'])
            }
        }

        json_matches = request.json() == expected
        basic_auth_header = request.headers.get('Authorization') == 'Bearer zendesksell-api-key'

        return json_matches and basic_auth_header

    with requests_mock.mock() as rmock:
        expected_note_id = '1'
        resp_data = {'data': {'id': expected_note_id}}
        rmock.request(
            "POST",
            url='https://zendesksell-test.com/v2/notes',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=200,
            text=json.dumps(resp_data)
        )

        data = {
            'email_address': "test@email.com",
            'service_name': 'service_name',
            'department_org_name': 'department_org_name',
            'intended_recipients': 'intended_recipients',
            'main_use_case': 'main_use_case',
            'notification_types': 'notification_types',
            'expected_volume': 'expected_volume',
            'service_url': 'service_url',
            'support_type': 'go_live_request'
        }

        with notify_api.app_context():
            note_id = ZenDeskSell().create_note(ZenDeskSell.NoteResourceType.DEAL, resource_id, ContactRequest(**data))
            assert expected_note_id == note_id


@pytest.mark.parametrize('expected_resp_data', [
    {'blank': 'blank'},
    {'data': {'blank': 'blank'}},
])
def test_create_note_invalid_response(notify_api: Flask,
                                      sample_service: Service,
                                      expected_resp_data: Dict[str, Dict[str, Union[int, str]]]):

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            url='https://zendesksell-test.com/v2/notes',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            status_code=200,
            text=json.dumps(expected_resp_data)
        )

        data = {
            'email_address': "test@email.com",
            'service_name': 'service_name',
            'department_org_name': 'department_org_name',
            'intended_recipients': 'intended_recipients',
            'main_use_case': 'main_use_case',
            'notification_types': 'notification_types',
            'expected_volume': 'expected_volume',
            'service_url': 'service_url',
            'support_type': 'go_live_request'
        }

        with notify_api.app_context():
            note_id = ZenDeskSell().create_note(ZenDeskSell.NoteResourceType.DEAL, '1', ContactRequest(**data))
            assert not note_id


@pytest.mark.parametrize('is_go_live,existing_contact_id', [
    (False, None),
    (False, '1'),
    (True, None)
])
def test_create_service_or_go_live_contact_fail(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture,
        is_go_live: bool,
        existing_contact_id: Optional[str]
):

    upsert_contact_mock = mocker.patch('app.user.rest.ZenDeskSell.upsert_contact', return_value=(None, False))
    convert_lead_to_contact_mock = \
        mocker.patch('app.user.rest.ZenDeskSell.convert_lead_to_contact', return_value=existing_contact_id)

    with notify_api.app_context():
        if is_go_live:
            assert not ZenDeskSell().send_go_live_service(sample_service, sample_service.users[0])
            upsert_contact_mock.assert_called_once_with(sample_service.users[0], existing_contact_id)
        else:
            assert not ZenDeskSell().send_create_service(sample_service, sample_service.users[0])
            convert_lead_to_contact_mock.assert_called_once_with(sample_service.users[0])
            upsert_contact_mock.assert_called_once_with(sample_service.users[0], existing_contact_id)


@pytest.mark.parametrize('is_go_live,existing_contact_id', [
    (False, None),
    (False, '2'),
    (True, None)
])
def test_create_service_or_go_live_deal_fail(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture,
        is_go_live: bool,
        existing_contact_id: Optional[str]
):

    with requests_mock.mock() as rmock:
        contact_id = existing_contact_id or '1'
        rmock.request(
            contact_http_method(existing_contact_id),
            url=generate_contact_url(existing_contact_id, sample_service),
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            status_code=200,
            text=json.dumps({'data': {'id': contact_id, 'created_at': '1', 'updated_at': '1'}})
        )

        mocker.patch('app.user.rest.ZenDeskSell.upsert_deal', return_value=None)
        mocker.patch('app.user.rest.ZenDeskSell.convert_lead_to_contact', return_value=existing_contact_id)
        contact_delete_mock = mocker.patch('app.user.rest.ZenDeskSell.delete_contact')
        with notify_api.app_context():
            if is_go_live:
                assert not ZenDeskSell().send_go_live_service(sample_service, sample_service.users[0])
            else:
                assert not ZenDeskSell().send_create_service(sample_service, sample_service.users[0])

            contact_delete_mock.assert_called_once_with(contact_id)


@pytest.mark.parametrize('is_go_live,existing_contact_id', [
    (False, None),
    (False, '1'),
    (True, None)
])
def test_create_service_or_go_live_deal_fail_contact_exists(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture,
        is_go_live: bool,
        existing_contact_id: Optional[str]
):
    with requests_mock.mock() as rmock:
        contact_id = existing_contact_id or '1'
        rmock.request(
            contact_http_method(existing_contact_id),
            url=generate_contact_url(existing_contact_id, sample_service),
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            status_code=200,
            text=json.dumps({'data': {'id': contact_id, 'created_at': '1', 'updated_at': '2'}})
        )

        mocker.patch('app.user.rest.ZenDeskSell.upsert_deal', return_value=None)
        mocker.patch('app.user.rest.ZenDeskSell.convert_lead_to_contact', return_value=existing_contact_id)
        contact_delete_mock = mocker.patch('app.user.rest.ZenDeskSell.delete_contact')
        with notify_api.app_context():
            if is_go_live:
                assert not ZenDeskSell().send_go_live_service(sample_service, sample_service.users[0])
            else:
                assert not ZenDeskSell().send_create_service(sample_service, sample_service.users[0])

            contact_delete_mock.assert_not_called()


@pytest.mark.parametrize('existing_contact_id', [None, '2'])
def test_send_create_service(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture,
        existing_contact_id: Optional[str]):

    contact_id = existing_contact_id or '1'
    upsert_contact_mock = mocker.patch('app.user.rest.ZenDeskSell.upsert_contact', return_value=(contact_id, True))
    convert_lead_to_contact_mock = \
        mocker.patch('app.user.rest.ZenDeskSell.convert_lead_to_contact', return_value=existing_contact_id)
    upsert_deal_mock = mocker.patch('app.user.rest.ZenDeskSell.upsert_deal', return_value=1)
    with notify_api.app_context():
        assert ZenDeskSell().send_create_service(sample_service, sample_service.users[0])
        convert_lead_to_contact_mock.assert_called_once_with(sample_service.users[0])
        upsert_contact_mock.assert_called_once_with(sample_service.users[0], existing_contact_id)
        upsert_deal_mock.assert_called_once_with(contact_id, sample_service, ZenDeskSell.STATUS_CREATE_TRIAL)


def test_send_go_live_request(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture):
    deal_id = '1'
    search_deal_id_mock = mocker.patch('app.user.rest.ZenDeskSell.search_deal_id', return_value=deal_id)
    send_create_service_mock = mocker.patch('app.user.rest.ZenDeskSell.send_create_service', return_value='1')
    create_note_mock = mocker.patch('app.user.rest.ZenDeskSell.create_note', return_value='2')

    contact = ContactRequest(**{
        'email_address': "test@email.com",
        'service_name': 'service_name',
        'department_org_name': 'department_org_name',
        'intended_recipients': 'intended_recipients',
        'main_use_case': 'main_use_case',
        'notification_types': 'notification_types',
        'expected_volume': 'expected_volume',
        'service_url': 'service_url',
        'support_type': 'go_live_request'
    })

    with notify_api.app_context():
        assert ZenDeskSell().send_go_live_request(sample_service, sample_service.users[0], contact)
        search_deal_id_mock.assert_called_once_with(sample_service)
        send_create_service_mock.assert_not_called()
        create_note_mock.assert_called_once_with(ZenDeskSell.NoteResourceType.DEAL, deal_id, contact)


def test_send_go_live_request_search_failed(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture):
    deal_id = '1'
    search_deal_id_mock = mocker.patch('app.user.rest.ZenDeskSell.search_deal_id', return_value=None)
    send_create_service_mock = mocker.patch('app.user.rest.ZenDeskSell.send_create_service', return_value=deal_id)
    create_note_mock = mocker.patch('app.user.rest.ZenDeskSell.create_note', return_value='1')

    contact = ContactRequest(**{
        'email_address': "test@email.com",
        'service_name': 'service_name',
        'department_org_name': 'department_org_name',
        'intended_recipients': 'intended_recipients',
        'main_use_case': 'main_use_case',
        'notification_types': 'notification_types',
        'expected_volume': 'expected_volume',
        'service_url': 'service_url',
        'support_type': 'go_live_request'
    })

    with notify_api.app_context():
        assert ZenDeskSell().send_go_live_request(sample_service, sample_service.users[0], contact)
        search_deal_id_mock.assert_called_once_with(sample_service)
        send_create_service_mock.assert_called_once_with(sample_service, sample_service.users[0])
        create_note_mock.assert_called_once_with(ZenDeskSell.NoteResourceType.DEAL, deal_id, contact)


def test_send_go_live_service(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture):

    contact_id = 1
    upsert_contact_mock = mocker.patch('app.user.rest.ZenDeskSell.upsert_contact', return_value=(contact_id, True))
    upsert_deal_mock = mocker.patch('app.user.rest.ZenDeskSell.upsert_deal', return_value=1)
    with notify_api.app_context():
        assert ZenDeskSell().send_go_live_service(sample_service, sample_service.users[0])
        upsert_contact_mock.assert_called_once_with(sample_service.users[0], None)
        upsert_deal_mock.assert_called_once_with(contact_id, sample_service, ZenDeskSell.STATUS_CLOSE_LIVE)
