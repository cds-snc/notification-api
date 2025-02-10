import copy
from logging import Logger
from time import monotonic
from typing_extensions import TypedDict

import requests
from requests.auth import HTTPBasicAuth
from notifications_utils.clients.statsd.statsd_client import StatsdClient

from app.celery.exceptions import NonRetryableException, RetryableException
from app.v2.dataclasses import V2PushPayload


class Credentials(TypedDict):
    username: str
    password: str


class VETextClient:
    STATSD_KEY = 'clients.vetext'
    TIMEOUT = 3.05

    def init_app(
        self,
        url: str,
        credentials: Credentials,
        logger: Logger,
        statsd: StatsdClient,
    ):
        self.base_url = url
        self.auth = HTTPBasicAuth(**credentials)
        self.logger = logger
        self.statsd = statsd

    @staticmethod
    def format_for_vetext(payload: V2PushPayload) -> dict[str, str]:
        if payload.personalisation:
            payload.personalisation = {f'%{k.upper()}%': v for k, v in payload.personalisation.items()}

        formatted_payload = {
            'appSid': payload.app_sid,
            'templateSid': payload.template_id,
            'personalization': payload.personalisation,
        }

        if payload.is_broadcast():
            formatted_payload['topicSid'] = payload.topic_sid
        else:
            formatted_payload['icn'] = payload.icn

        return formatted_payload

    def send_push_notification(
        self,
        payload: dict[str, str],
    ) -> None:
        """Send the notification to VEText and handle any errors.

        Args:
            payload (dict[str, str]): The data to send to VEText
        """
        self.logger.debug('VEText Payload information %s', payload)
        start_time = monotonic()
        try:
            response = requests.post(
                f'{self.base_url}/mobile/push/send', auth=self.auth, json=payload, timeout=self.TIMEOUT
            )

            self.logger.info('VEText response: %s', response.json() if response.ok else response.status_code)
            self.logger.debug(
                'VEText response: %s for payload %s', response.json() if response.ok else response.status_code, payload
            )
            response.raise_for_status()
        except requests.exceptions.ReadTimeout:
            # Discussion with VEText: read timeouts are still processed, so no need to retry
            self.logger.info('ReadTimeout raised sending push notification - notification still processed')
            self.statsd.incr(f'{self.STATSD_KEY}.error.read_timeout')
        except requests.exceptions.ConnectTimeout as e:
            self.logger.warning('ConnectTimeout raised sending push notification - Retrying')
            self.statsd.incr(f'{self.STATSD_KEY}.error.connection_timeout')
            raise RetryableException from e
        except requests.HTTPError as e:
            self.statsd.incr(f'{self.STATSD_KEY}.error.{e.response.status_code}')
            if e.response.status_code in [429, 500, 502, 503, 504]:
                self.logger.warning('Retryable exception raised with status code %s', e.response.status_code)
                raise RetryableException from e
            elif e.response.status_code == 400:
                self._decode_bad_request_response(e)
            else:
                redacted_payload = copy.deepcopy(payload)
                if 'icn' in redacted_payload:
                    redacted_payload['icn'] = '<redacted>'

                self.logger.exception(
                    'Status: %s - Not retrying - payload: %s',
                    e.response.status_code,
                    redacted_payload,
                )
                raise NonRetryableException from e
        except requests.RequestException as e:
            redacted_payload = copy.deepcopy(payload)
            if 'icn' in redacted_payload:
                redacted_payload['icn'] = '<redacted>'

            self.logger.exception(
                'Exception raised sending push notification. Not retrying - payload: %s',
                redacted_payload,
            )
            self.statsd.incr(f'{self.STATSD_KEY}.error.request_exception')
            raise NonRetryableException from e
        else:
            self.statsd.incr(f'{self.STATSD_KEY}.success')
        finally:
            elapsed_time = monotonic() - start_time
            self.statsd.timing(f'{self.STATSD_KEY}.request_time', elapsed_time)

    def _decode_bad_request_response(
        self,
        http_exception,
    ):
        """Parse the response and raise an exception as this is always an exception

        Args:
            http_exception (Exception): The exception raised

        Raises:
            NonRetryableException: Raised exception
        """
        try:
            payload = http_exception.response.json()
            field = payload.get('idType')
            message = payload.get('error')
            self.logger.error('Bad response from VEText: %s with field: ', message, field)
            raise NonRetryableException from http_exception
        except Exception:
            message = http_exception.response.text
            self.logger.error('Bad response from VEText: %s', message)
            raise NonRetryableException from http_exception
