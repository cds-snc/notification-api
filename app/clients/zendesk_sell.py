import json
import requests

from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin

from flask import current_app

from app.authentication.bearer_auth import BearerAuth
from app.user.contact_request import ContactRequest
from app.models import Service, User

__all__ = [
    'ZenDeskSell'
]


class ZenDeskSell(object):

    # FIXME: consider making this an environment variable
    OWNER_ID = 2693899

    STATUS_CREATE_TRIAL = 11826762
    STATUS_CLOSE_LIVE = 11826764

    def __init__(self):
        self.api_url = current_app.config['ZENDESK_SELL_API_URL']
        self.token = current_app.config['ZENDESK_SELL_API_KEY']

    @staticmethod
    def _name_split(name: str) -> (str, str):
        # FIXME: consider migrating to pypi/nameparser for proper name parsing to handle cases like:
        # 'Dr. Juan Q. Xavier de la Vega III (Doc Vega)'
        name_tokenised = name.split()
        return " ".join(name_tokenised[:-1]) if len(name_tokenised) > 1 else '', name_tokenised[-1]

    @staticmethod
    def _generate_lead_data(contact: ContactRequest) -> Dict[str, Union[str, List[str], Dict]]:

        # validation based upon api mandatory fields
        assert len(contact.name) or len(contact.department_org_name), 'Name or Org are mandatory field'

        recipients = {
            'internal': 'Colleagues within your department (internal)',
            'external': 'Partners from other organizations (external)',
            'public': 'Public'
        }

        first_name, last_name = ZenDeskSell._name_split(contact.name)
        return {
            'data': {
                'last_name': last_name,
                'first_name': first_name,
                'organization_name': contact.department_org_name,
                'owner_id': ZenDeskSell.OWNER_ID,
                'email': contact.email_address,
                'description': f'Program: {contact.program_service_name}\n{contact.main_use_case}: '
                               f'{contact.main_use_case_details}',
                'tags': [contact.support_type, contact.language],
                'status': 'New',
                'source_id': 2085874,  # hard coded value defined by Zendesk for 'Demo request form'
                'custom_fields': {
                    'Product': ['Notify'],
                    'Intended recipients': recipients[contact.intended_recipients]
                    if contact.intended_recipients in recipients else 'No value'
                }
            }
        }

    @staticmethod
    def _generate_contact_data(user: User) -> Dict[str, Union[str, List[str], Dict]]:

        # validation based upon api mandatory fields
        assert len(user.name) and len(user.email_address), 'Name or email are mandatory field'

        first_name, last_name = ZenDeskSell._name_split(user.name)
        return {
            'data': {
                'last_name': last_name,
                'first_name': first_name,
                'email': user.email_address,
                'mobile': user.mobile_number,
                'owner_id': ZenDeskSell.OWNER_ID,
                'custom_fields': {
                    'notify_user_id': str(user.id),
                }
            }
        }

    @staticmethod
    def _generate_deal_data(contact_id: int, service: Service, stage_id: int) -> Dict[str, Union[str, List[str], Dict]]:
        return {
            'data': {
                'contact_id': contact_id,
                'name': service.name,
                'stage_id': stage_id,
                'owner_id': ZenDeskSell.OWNER_ID,
                'custom_fields': {
                    'notify_service_id': str(service.id),
                }
            }
        }

    def _send_request(
            self,
            method: str,
            relative_url: str,
            data: str = None) -> (Optional[Any], Optional[Exception]):

        if not self.api_url or not self.token:
            raise NotImplementedError

        try:
            response = requests.request(
                method=method,
                url=urljoin(self.api_url, relative_url),
                data=data,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
                auth=BearerAuth(token=self.token),
                timeout=5
            )
            response.raise_for_status()
            return response, None
        except requests.RequestException as e:
            return response, e

    def upsert_lead(self, contact: ContactRequest) -> int:

        # The API and field definitions are defined here: https://developers.getbase.com/docs/rest/reference/leads

        # name is mandatory for zen desk sell API
        assert len(contact.name), 'Zendesk sell requires a name for its API'

        resp, e = self._send_request(method='POST',
                                     relative_url=f'/v2/leads/upsert?email={contact.email_address}',
                                     data=json.dumps(ZenDeskSell._generate_lead_data(contact)))
        if e:
            content = json.loads(resp.content)
            current_app.logger.warning(f"Failed to create zendesk sell lead: {content['errors']}")
            raise e

        return resp.status_code

    def upsert_contact(self, user: User) -> (Optional[int], bool):

        # The API and field definitions are defined here: https://developers.getbase.com/docs/rest/reference/contacts
        resp, e = self._send_request(method='POST',
                                     relative_url=f'/v2/contacts/upsert?'
                                                  f'custom_fields%5Bnotify_user_id%5D={str(user.id)}',
                                     data=json.dumps(ZenDeskSell._generate_contact_data(user)))
        if e:
            current_app.logger.warning('Failed to create zendesk sell contact')
            return None, False

        # response validation
        try:
            resp_data = resp.json()
            return resp_data['data']['id'], resp_data['data']['created_at'] == resp_data['data']['updated_at']

        except (json.JSONDecodeError, KeyError):
            current_app.logger.warning(f'Invalid response: {resp.text}')
            return None, False

    def delete_contact(self, contact_id: int) -> None:

        # The API and field definitions are defined here: https://developers.getbase.com/docs/rest/reference/contacts
        resp, e = self._send_request(method='DELETE',
                                     relative_url=f'/v2/contacts/{contact_id}')
        if e:
            current_app.logger.warning(f'Failed to delete zendesk sell contact: {contact_id}')

    def upsert_deal(self, contact_id: int, service: Service, stage_id: int) -> Optional[int]:
        # The API and field definitions are defined here: https://developers.getbase.com/docs/rest/reference/deals

        resp, e = self._send_request(
            method='POST',
            relative_url=f'/v2/deals/upsert?contact_id={contact_id}&'
                         f'custom_fields%5Bnotify_service_id%5D={str(service.id)}',
            data=json.dumps(ZenDeskSell._generate_deal_data(contact_id, service, stage_id)))

        if e:
            current_app.logger.warning('Failed to create zendesk sell deal')
            return None

        # response validation
        try:
            resp_data = resp.json()
            return resp_data['data']['id']

        except (json.JSONDecodeError, KeyError):
            current_app.logger.warning(f'Invalid response: {resp.text}')
            return None

    def _common_create_or_go_live(self, service: Service, user: User, status: int) -> bool:
        # Upsert a contact (create/update). Only when this is successful does the software upsert a deal
        # and link the deal to the contact.
        # If upsert deal fails go back and delete the contact ONLY if it never existed before
        contact_id, is_created = self.upsert_contact(user)
        if not contact_id:
            return False

        deal_id = self.upsert_deal(contact_id, service, status)
        if not deal_id and is_created:
            # best effort here
            self.delete_contact(contact_id)
            return False

        return deal_id is not None

    def send_go_live_service(self, service: Service, user: User) -> bool:
        return self._common_create_or_go_live(service, user, ZenDeskSell.STATUS_CLOSE_LIVE)

    def send_create_service(self, service: Service, user: User) -> bool:
        return self._common_create_or_go_live(service, user, ZenDeskSell.STATUS_CREATE_TRIAL)

    def send_contact_request(self, contact: ContactRequest) -> int:
        ret = 200
        if contact.is_demo_request():
            ret = self.upsert_lead(contact)

        return ret
