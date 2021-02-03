import base64

import requests_mock

from app.clients.freshdesk import Freshdesk


def test_create_ticket(notify_api):
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
            'https://example.com/freshdesk/api/v2/tickets',
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
