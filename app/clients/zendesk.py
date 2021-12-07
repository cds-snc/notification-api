import json
from typing import Dict, List, Union
from urllib.parse import urljoin

import requests
from flask import current_app
from requests.auth import HTTPBasicAuth

from app.user.contact_request import ContactRequest

__all__ = ["Zendesk"]


class Zendesk(object):

    # added from zendesk_sell code
    def __init__(self, contact: ContactRequest):
        self.api_url = current_app.config["ZENDESK_API_URL"]
        self.token = current_app.config["ZENDESK_API_KEY"]
        self.contact = contact

    def init(self, contact: ContactRequest):
        self.contact = contact

    def _generate_description(self):
        message = self.contact.message
        if self.contact.is_go_live_request():
            message = "<br>".join(
                [
                    f"{self.contact.service_name} just requested to go live.",
                    "",
                    f"- Department/org: {self.contact.department_org_name}",
                    f"- Intended recipients: {self.contact.intended_recipients}",
                    f"- Purpose: {self.contact.main_use_case}",
                    f"- Notification types: {self.contact.notification_types}",
                    f"- Expected monthly volume: {self.contact.expected_volume}",
                    "---",
                    self.contact.service_url,
                ]
            )
        elif self.contact.is_branding_request():
            message = "<br>".join(
                [
                    f"A new logo has been uploaded by {self.contact.name} ({self.contact.email_address}) for the following service:",
                    f"- Service id: {self.contact.service_id}",
                    f"- Service name: {self.contact.service_name}",
                    f"- Logo filename: {self.contact.branding_url}",
                    "<hr>",
                    f"Un nouveau logo a été téléchargé par {self.contact.name} ({self.contact.email_address}) pour le service suivant :",
                    f"- Identifiant du service : {self.contact.service_id}",
                    f"- Nom du service : {self.contact.service_name}",
                    f"- Nom du fichier du logo : {self.contact.branding_url}",
                ]
            )

        if len(self.contact.user_profile):
            message += f"<br><br>---<br><br> {self.contact.user_profile}"

        return message

    # Update for Zendesk API Ticket format
    # read docs: https://developer.zendesk.com/rest_api/docs/core/tickets#create-ticket
    def _generate_ticket(self) -> Dict[str, Dict[str, Union[str, int, List[str]]]]:

        return {
            "ticket": {
                "subject": self.contact.friendly_support_type,
                "description": self._generate_description(),
                "email": self.contact.email_address,
                "priority": 1,
                "tags": ["notification_api"],  # Tag used to auto-assign ticket to the notification support group
            }
        }

    def send_ticket(self) -> int:
        try:
            if not self.api_url or not self.token:
                raise NotImplementedError

            # The API and field definitions are defined here:
            # https://developer.zendesk.com/rest_api/docs/support/tickets
            response = requests.post(
                urljoin(self.api_url, "/api/v2/tickets"),
                json=self._generate_ticket(),
                auth=HTTPBasicAuth(f"{self.contact.email_address}/token", self.token),
                timeout=5,
            )
            response.raise_for_status()
            return response, None
        except requests.RequestException as e:
            return response, e
