import json

import requests
from requests.auth import HTTPBasicAuth

from flask import current_app


class Freshdesk(object):
    @staticmethod
    def create_ticket(data):
        ticket = {
            'product_id': 61000000046,
            'subject': data.get("support_type", "Support Request"),
            'description': data["message"],
            'email': data["email"],
            'priority': 1,
            'status': 2,
            'tags': data.get("tags"),
        }

        try:
            response = requests.post(
                f"{current_app.config['FRESH_DESK_API_URL']}/api/v2/tickets",
                json=ticket,
                auth=HTTPBasicAuth(current_app.config['FRESH_DESK_API_KEY'], "x")
            )
            response.raise_for_status()

            return response.status_code
        except requests.RequestException as e:
            content = json.loads(response.content)
            current_app.logger.warning(f"Failed to create Freshdesk ticket: {content['errors']}")
            raise e
