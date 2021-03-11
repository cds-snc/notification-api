import requests_mock

from flask import Flask

from app.clients.zendesk_sell_client import ZenDeskSellClient
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
                'tags': ["Support Request", "en"],
                'status': 'New',
                'custom_fields': {
                    'Product': ['Notify'],
                    'Source': 'Demo request form',
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
            url='https://example.com/zendesksell/v2/leads/upsert?email=test@email.com',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            additional_matcher=match_json,
            status_code=201
        )

        with notify_api.app_context():
            data = {'email_address': "test@email.com", 'name': 'Test User'}
            response = ZenDeskSellClient(ContactRequest(**data)).send_lead()
            assert response == 201


def test_create_lead_missing_name(notify_api: Flask):
    with notify_api.app_context():
        try:
            ZenDeskSellClient(ContactRequest(**{'email_address': 'test@email.com'})).send_lead()
        except Exception as e:
            assert isinstance(e, AssertionError)
