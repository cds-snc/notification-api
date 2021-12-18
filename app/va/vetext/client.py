from typing import Dict
from typing_extensions import TypedDict
from requests.auth import HTTPBasicAuth
import requests


class Credentials(TypedDict):
    username: str
    password: str


class VETextClient:
    def init_app(self, url: str, credentials: Credentials):
        self.base_url = url
        self.auth = HTTPBasicAuth(**credentials)

    def send_push_notification(self, mobile_app: str, template_id: str, icn: str, personalisation: Dict = None) -> None:
        payload = {
            "appSid": mobile_app,
            "icn": icn,
            "templateSid": template_id,
            "personalization": personalisation
        }

        try:
            response = requests.post(
                f"{self.base_url}/mobile/push/send",
                auth=self.auth,
                json=payload
            )
            response.raise_for_status()
        except requests.HTTPError:
            pass
        except requests.RequestException:
            pass
