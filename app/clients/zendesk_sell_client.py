import json
import requests

from typing import Dict, List, Union

from flask import current_app

from app.authentication.bearer_auth import BearerAuth
from app.user.contact_request import ContactRequest

__all__ = [
    'ZenDeskSellClient'
]


class ZenDeskSellClient(object):

    def _generate_lead_data(self) -> Dict[str, Union[str, List[str], Dict]]:

        # The API and field definitions are defined here: https://developers.getbase.com/docs/rest/reference/leads

        # validation based upon api mandatory fields
        assert len(self.contact.name) or len(self.contact.department_org_name), 'Name or Org are mandatory field'

        recipients = {
            'internal': 'Colleagues within your department (internal)',
            'external': 'Partners from other organizations (external)',
            'public': 'Public'
        }
        # FIXME: consider migrating to pypi/nameparser for proper name parsing to handle cases like:
        # 'Dr. Juan Q. Xavier de la Vega III (Doc Vega)'
        name_tokenised = self.contact.name.split()
        return {
            'data': {
                'last_name': name_tokenised[-1],
                'first_name': " ".join(name_tokenised[:-1]) if len(name_tokenised) > 1 else '',
                'organization_name': self.contact.department_org_name,
                'email': self.contact.email_address,
                'description': f'Program: {self.contact.program_service_name}\n{self.contact.main_use_case}: '
                               f'{self.contact.main_use_case_details}',
                'tags': [self.contact.support_type, self.contact.language],
                'status': 'New',
                'custom_fields': {
                    'Product': ['Notify'],
                    'Source': 'Demo request form',
                    'Intended recipients': recipients[self.contact.intended_recipients]
                    if self.contact.intended_recipients in recipients else 'No value'
                }
            }
        }

    def __init__(self, contact: ContactRequest):
        self.api_url = current_app.config['ZEN_DESK_SELL_API_URL']
        self.token = current_app.config['ZEN_DESK_SELL_API_KEY']
        self.contact = contact

    def send_contact_request(self) -> int:
        # FIXME: as a POC we will only send leads when a user requests a demo
        # FIXME: remove this condition when we want to use zen desk sell fully for all inquiries
        ret = 200
        if 'demo' in self.contact.support_type.lower():
            ret = self.send_lead()

        return ret

    def send_lead(self) -> int:
        # name is mandatory for zen desk sell API
        assert len(self.contact.name), 'Zendesk sell requires a name for its API'

        try:
            if not self.api_url or not self.token:
                raise NotImplementedError

            payload = self._generate_lead_data()
            headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}

            response = requests.post(
                url=f'{self.api_url}/v2/leads/upsert?email={self.contact.email_address}',
                data=json.dumps(payload),
                headers=headers,
                auth=BearerAuth(token=self.token),
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

        return 400
