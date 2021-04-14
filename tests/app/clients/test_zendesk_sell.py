import json
import pytest
import requests_mock

from flask import Flask
from pytest_mock import MockFixture
from typing import Dict, Union

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


def test_create_contact(notify_api: Flask, sample_service: Service):

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
        resp_data = {
            'data': {
                'id': 123456789,
                'created_at': '2021-03-24T14:49:38Z',
                'updated_at': '2021-03-24T14:49:38Z'
            }
        }
        rmock.request(
            "POST",
            url=f'https://zendesksell-test.com/v2/contacts/upsert?'
                f'custom_fields[notify_user_id]={str(sample_service.users[0].id)}',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=200,
            text=json.dumps(resp_data)

        )
        with notify_api.app_context():
            contact_id, is_created = ZenDeskSell().upsert_contact(sample_service.users[0])
            assert contact_id == 123456789
            assert is_created


def test_upsert_contact(notify_api: Flask, sample_service: Service):

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
        # the created_at and updated_at values are different
        resp_data = {
            'data': {
                'id': 123456789,
                'created_at': '2021-02-24T14:49:38Z',
                'updated_at': '2021-03-24T14:49:38Z'
            }
        }
        rmock.request(
            "POST",
            url=f'https://zendesksell-test.com/v2/contacts/upsert?'
                f'custom_fields[notify_user_id]={str(sample_service.users[0].id)}',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=200,
            text=json.dumps(resp_data)

        )
        with notify_api.app_context():
            contact_id, is_created = ZenDeskSell().upsert_contact(sample_service.users[0])
            assert contact_id == 123456789
            assert not is_created


@pytest.mark.parametrize('expected_resp_data', [
    {'blank': 'blank'},
    {'data': {'created_at': '2021-02-24T14:49:38Z', 'updated_at': '2021-03-24T14:49:38Z'}},
    {'data': {'id': 123456789, 'created_at': '2021-02-24T14:49:38Z'}},
    {'data': {'id': 123456789, 'updated_at': '2021-02-24T14:49:38Z'}}
])
def test_create_contact_invalid_response(notify_api: Flask,
                                         sample_service: Service,
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
            "POST",
            url=f'https://zendesksell-test.com/v2/contacts/upsert?'
                f'custom_fields[notify_user_id]={str(sample_service.users[0].id)}',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=200,
            text=json.dumps(expected_resp_data)

        )
        with notify_api.app_context():
            contact_id, _ = ZenDeskSell().upsert_contact(sample_service.users[0])
            assert not contact_id


def test_delete_contact(notify_api: Flask):
    def match_header(request):
        return request.headers.get('Authorization') == 'Bearer zendesksell-api-key'

    with requests_mock.mock() as rmock:
        contact_id = 123456789
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
                'contact_id': 123456789,
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
        contact_id = 123456789
        expected_deal_id = 987654321
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
                'contact_id': 123456789,
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
        contact_id = 123456789
        rmock.request(
            "POST",
            url=f'https://zendesksell-test.com/v2/deals/upsert?contact_id={contact_id}'
                f'&custom_fields%5Bnotify_service_id%5D={str(sample_service.id)}',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=200,
            text=json.dumps(expected_resp_data)
        )

        with notify_api.app_context():
            deal_id = ZenDeskSell().upsert_deal(contact_id, sample_service, 123456789)
            assert not deal_id


def test_common_create_or_go_live_contact_fail(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture):

    upsert_contact_mock = mocker.patch('app.user.rest.ZenDeskSell.upsert_contact', return_value=(None, False))
    with notify_api.app_context():
        assert not ZenDeskSell()._common_create_or_go_live(sample_service, sample_service.users[0], 1)
        upsert_contact_mock.assert_called()


def test_common_create_or_go_live_deal_fail(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture):

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            url=f'https://zendesksell-test.com/v2/contacts/upsert?'
                f'custom_fields[notify_user_id]={str(sample_service.users[0].id)}',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            status_code=200,
            text=json.dumps({'data': {'id': 1, 'created_at': '1', 'updated_at': '1'}})
        )

        mocker.patch('app.user.rest.ZenDeskSell.upsert_deal', return_value=None)
        contact_delete_mock = mocker.patch('app.user.rest.ZenDeskSell.delete_contact')
        with notify_api.app_context():
            assert not ZenDeskSell()._common_create_or_go_live(sample_service, sample_service.users[0], 1)
            contact_delete_mock.assert_called()


def test_common_create_or_go_live_deal_fail_contact_exists(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture):
    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            url=f'https://zendesksell-test.com/v2/contacts/upsert?'
                f'custom_fields[notify_user_id]={str(sample_service.users[0].id)}',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            status_code=200,
            text=json.dumps({'data': {'id': 1, 'created_at': '1', 'updated_at': '2'}})
        )

        mocker.patch('app.user.rest.ZenDeskSell.upsert_deal', return_value=None)
        contact_delete_mock = mocker.patch('app.user.rest.ZenDeskSell.delete_contact')
        with notify_api.app_context():
            assert not ZenDeskSell()._common_create_or_go_live(sample_service, sample_service.users[0], 1)
            contact_delete_mock.assert_not_called()


def test_send_create_service(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture):

    upsert_contact_mock = mocker.patch('app.user.rest.ZenDeskSell.upsert_contact', return_value=(1, True))
    upsert_deal_mock = mocker.patch('app.user.rest.ZenDeskSell.upsert_deal', return_value=1)
    with notify_api.app_context():
        assert ZenDeskSell().send_create_service(sample_service, sample_service.users[0])
        upsert_contact_mock.assert_called()
        upsert_deal_mock.assert_called()


def test_send_go_live_service(
        notify_api: Flask,
        sample_service: Service,
        mocker: MockFixture):

    upsert_contact_mock = mocker.patch('app.user.rest.ZenDeskSell.upsert_contact', return_value=(1, True))
    upsert_deal_mock = mocker.patch('app.user.rest.ZenDeskSell.upsert_deal', return_value=1)
    with notify_api.app_context():
        assert ZenDeskSell().send_go_live_service(sample_service, sample_service.users[0])
        upsert_contact_mock.assert_called()
        upsert_deal_mock.assert_called()
