import json
import requests

from typing import Dict, List, Union
from urllib.parse import urljoin

from flask import current_app

from app.authentication.bearer_auth import BearerAuth
from app.user.contact_request import ContactRequest

__all__ = [
    'ZenDeskSell'
]


class ZenDeskSell(object):

    def __init__(self):
        self.api_url = current_app.config['ZENDESK_SELL_API_URL']
        self.token = current_app.config['ZENDESK_SELL_API_KEY']

    @staticmethod
    def _generate_lead_data(contact: ContactRequest) -> Dict[str, Union[str, List[str], Dict]]:

        # The API and field definitions are defined here: https://developers.getbase.com/docs/rest/reference/leads

        # validation based upon api mandatory fields
        assert len(contact.name) or len(contact.department_org_name), 'Name or Org are mandatory field'

        recipients = {
            'internal': 'Colleagues within your department (internal)',
            'external': 'Partners from other organizations (external)',
            'public': 'Public'
        }
        # FIXME: consider migrating to pypi/nameparser for proper name parsing to handle cases like:
        # 'Dr. Juan Q. Xavier de la Vega III (Doc Vega)'
        name_tokenised = contact.name.split()
        return {
            'data': {
                'last_name': name_tokenised[-1],
                'first_name': " ".join(name_tokenised[:-1]) if len(name_tokenised) > 1 else '',
                'organization_name': contact.department_org_name,
                'email': contact.email_address,
                'description': f'Program: {contact.program_service_name}\n{contact.main_use_case}: '
                               f'{contact.main_use_case_details}',
                'tags': [contact.support_type, contact.language],
                'status': 'New',
                'custom_fields': {
                    'Product': ['Notify'],
                    'Source': 'Demo request form',
                    'Intended recipients': recipients[contact.intended_recipients]
                    if contact.intended_recipients in recipients else 'No value'
                }
            }
        }

    def send_contact_request(self, contact: ContactRequest) -> int:
        ret = 200
        if contact.is_demo_request():
            ret = self.send_lead(contact)

        return ret

    def send_lead(self, contact: ContactRequest) -> int:
        # name is mandatory for zen desk sell API
        assert len(contact.name), 'Zendesk sell requires a name for its API'

        try:
            if not self.api_url or not self.token:
                raise NotImplementedError

            response = requests.post(
                url=urljoin(self.api_url, f'/v2/leads/upsert?email={contact.email_address}'),
                data=json.dumps(ZenDeskSell._generate_lead_data(contact)),
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
                auth=BearerAuth(token=self.token),
                timeout=30.0
            )
            response.raise_for_status()

            return response.status_code
        except requests.RequestException as e:
            content = json.loads(response.content)
            self.app.logger.warning(f"Failed to create zendesk sell lead: {content['errors']}")
            raise e
        except NotImplementedError:
            # There are cases in development when we do not want to send to zendesk sell lead creation
            # because configuration is not defined, lets return a 200 OK
            self.app.logger.warning('Did not send lead to zendesk')
            return 200
