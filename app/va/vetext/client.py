import requests
from logging import Logger
from typing import Dict
from typing_extensions import TypedDict
from time import monotonic
from requests.auth import HTTPBasicAuth
from notifications_utils.clients.statsd.statsd_client import StatsdClient
from . import VETextRetryableException, VETextNonRetryableException, VETextBadRequestException


class Credentials(TypedDict):
    username: str
    password: str


class VETextClient:
    STATSD_KEY = "clients.vetext"
    TIMEOUT = 5

    def init_app(self, url: str, credentials: Credentials, logger: Logger, statsd: StatsdClient):
        self.base_url = url
        self.auth = HTTPBasicAuth(**credentials)
        self.logger = logger
        self.statsd = statsd

    def send_push_notification(self, mobile_app: str, template_id: str, icn: str, personalization: Dict = None) -> None:
        formatted_personalization = None
        if personalization:
            formatted_personalization = {}
            for key, value in personalization.items():
                formatted_personalization[f'%{key.upper()}%'] = value

        payload = {
            "appSid": mobile_app,
            "icn": icn,
            "templateSid": template_id,
            "personalization": formatted_personalization
        }
        self.logger.info(f'VEText Payload information: {payload}')

        try:
            start_time = monotonic()
            response = requests.post(
                f"{self.base_url}/mobile/push/send",
                auth=self.auth,
                json=payload,
                timeout=self.TIMEOUT
            )
            self.logger.info(f'VEText response: {response.json() if response.ok else response.status_code }')
            response.raise_for_status()
        except requests.HTTPError as e:
            self.logger.exception(e)
            self.statsd.incr(f"{self.STATSD_KEY}.error.{e.response.status_code}")
            if e.response.status_code in [429, 500, 502, 503, 504]:
                raise VETextRetryableException from e
                # TODO: add retries?
            elif e.response.status_code == 400:
                self._decode_bad_request_response(e)
            else:
                raise VETextNonRetryableException from e
        except requests.RequestException as e:
            self.logger.exception(e)
            self.statsd.incr(f"{self.STATSD_KEY}.error.request_exception")
            raise VETextRetryableException from e
            # TODO: add retries?
        else:
            self.statsd.incr(f"{self.STATSD_KEY}.success")
        finally:
            elapsed_time = monotonic() - start_time
            self.statsd.timing(f"{self.STATSD_KEY}.request_time", elapsed_time)

    def _decode_bad_request_response(self, http_exception):
        try:
            payload = http_exception.response.json()
        except Exception:
            message = http_exception.response.text
            raise VETextBadRequestException(message=message) from http_exception
        else:
            field = payload.get("idType")
            message = payload.get("error")
            raise VETextBadRequestException(field=field, message=message) from http_exception
