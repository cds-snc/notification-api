import base64

import requests_mock

from flask import Flask

from app.clients.freshdesk import Freshdesk
from app.user.contact_request import ContactRequest


def test_create_ticket_legacy(notify_api: Flask):
    def match_json(request):
        expected = {
            'product_id': 42,
            'subject': 'Ask a question',
            'description': 'my message',
            'email': 'test@example.com',
            'priority': 1,
            'status': 2,
            'tags': []
        }

        encoded_auth = base64.b64encode(b'freshdesk-api-key:x').decode('ascii')
        json_matches = request.json() == expected
        basic_auth_header = request.headers.get('Authorization') == f"Basic {encoded_auth}"

        return json_matches and basic_auth_header

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            'https://freshdesk-test.com/api/v2/tickets',
            additional_matcher=match_json,
            status_code=201
        )

        with notify_api.app_context():
            response = Freshdesk.create_ticket({
                'message': 'my message',
                'email': 'test@example.com',
                'support_type': 'Ask a question',
            })

            assert response == 201


def test_create_ticket_demo(notify_api: Flask):
    def match_json(request):
        expected = {
            'product_id': 42,
            'subject': 'demo',
            "description": '- user: name-test test@email.com<br><br>'
                           '- department/org: dept-test<br><br>'
                           '- program/service: service-test<br><br>'
                           '- intended recipients: internal<br><br>'
                           '- main use case: main-use-case-test<br><br>'
                           '- main use case details: main-use-case-details-test',
            'email': 'test@email.com',
            'priority': 1,
            'status': 2,
            'tags': []
        }

        encoded_auth = base64.b64encode(b'freshdesk-api-key:x').decode('ascii')
        json_matches = request.json() == expected
        basic_auth_header = request.headers.get('Authorization') == f"Basic {encoded_auth}"

        return json_matches and basic_auth_header

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            'https://freshdesk-test.com/api/v2/tickets',
            additional_matcher=match_json,
            status_code=201
        )

        contact_request = {
            'email_address': 'test@email.com',
            'name': 'name-test',
            'department_org_name': 'dept-test',
            'program_service_name': 'service-test',
            'intended_recipients': 'internal',
            'main_use_case': 'main-use-case-test',
            'main_use_case_details': 'main-use-case-details-test',
            'friendly_support_type': 'friendly-support-type-test',
            'language': 'en',
            'support_type': 'demo'
        }

        with notify_api.app_context():
            response = Freshdesk(ContactRequest(**contact_request)).send_ticket()
            assert response == 201


def test_create_ticket_other(notify_api: Flask):
    def match_json(request):
        expected = {
            'product_id': 42,
            'subject': 'Support Request',
            'description': '',
            'email': 'test@email.com',
            'priority': 1,
            'status': 2,
            'tags': []
        }

        encoded_auth = base64.b64encode(b'freshdesk-api-key:x').decode('ascii')
        json_matches = request.json() == expected
        basic_auth_header = request.headers.get('Authorization') == f"Basic {encoded_auth}"

        return json_matches and basic_auth_header

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            'https://freshdesk-test.com/api/v2/tickets',
            additional_matcher=match_json,
            status_code=201
        )

        with notify_api.app_context():
            response = Freshdesk(ContactRequest(**{'email_address': "test@email.com"})).send_ticket()
            assert response == 201


def test_create_ticket_user_profile(notify_api: Flask):
    def match_json(request):
        expected = {
            'product_id': 42,
            'subject': 'Support Request',
            'description': '<br><br>---<br><br> user_profile',
            'email': 'test@email.com',
            'priority': 1,
            'status': 2,
            'tags': []
        }

        encoded_auth = base64.b64encode(b'freshdesk-api-key:x').decode('ascii')
        json_matches = request.json() == expected
        basic_auth_header = request.headers.get('Authorization') == f"Basic {encoded_auth}"

        return json_matches and basic_auth_header

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            'https://freshdesk-test.com/api/v2/tickets',
            additional_matcher=match_json,
            status_code=201
        )

        with notify_api.app_context():
            response = Freshdesk(ContactRequest(**{'email_address': "test@email.com",
                                                   'user_profile': 'user_profile'})).send_ticket()
            assert response == 201
