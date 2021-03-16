import json
import requests

from requests.auth import HTTPBasicAuth
from typing import Dict, List, Union
from urllib.parse import urljoin

from flask import current_app

from app.user.contact_request import ContactRequest


__all__ = [
    'Freshdesk'
]


class Freshdesk(object):

    def __init__(self, contact: ContactRequest):
        self.contact = contact

    def _generate_description(self):
        message = self.contact.message
        if self.contact.is_demo_request():
            message = '<br><br>'.join([
                f'- user: {self.contact.name} {self.contact.email_address}',
                f'- department/org: {self.contact.department_org_name}',
                f'- program/service: {self.contact.program_service_name}',
                f'- intended recipients: {self.contact.intended_recipients}',
                f'- main use case: {self.contact.main_use_case}',
                f'- main use case details: {self.contact.main_use_case_details}',
            ])

        if len(self.contact.user_profile):
            message += f"<br><br>---<br><br> {self.contact.user_profile}"

        return message

    def _generate_ticket(self) -> Dict[str, Union[str, int, List[str]]]:

        product_id = current_app.config['FRESH_DESK_PRODUCT_ID']
        if not product_id:
            raise NotImplementedError

        return {
            'product_id': int(product_id),
            'subject': self.contact.support_type,
            'description': self._generate_description(),
            'email': self.contact.email_address,
            'priority': 1,
            'status': 2,
            'tags': self.contact.tags
        }

    def send_ticket(self) -> int:
        try:
            api_url = current_app.config['FRESH_DESK_API_URL']
            if not api_url:
                raise NotImplementedError

            # The API and field definitions are defined here:
            # https://developer.zendesk.com/rest_api/docs/support/tickets
            response = requests.post(
                urljoin(api_url, '/api/v2/tickets'),
                json=self._generate_ticket(),
                auth=HTTPBasicAuth(current_app.config['FRESH_DESK_API_KEY'], "x"),
                timeout=5
            )
            response.raise_for_status()

            return response.status_code
        except requests.RequestException as e:
            content = json.loads(response.content)
            current_app.logger.warning(f"Failed to create Freshdesk ticket: {content['errors']}")
            raise e
        except NotImplementedError:
            # There are cases in development when we do not want to send to freshdesk
            # because configuration is not defined, lets return a 200 OK
            current_app.logger.warning('Did not send ticket to Freshdesk')
            return 200

    @staticmethod
    def create_ticket(data):
        ticket = {
            'product_id': int(current_app.config['FRESH_DESK_PRODUCT_ID']),
            'subject': data.get("support_type", "Support Request"),
            'description': data["message"],
            'email': data["email"],
            'priority': 1,
            'status': 2,
            'tags': data.get("tags", []),
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
