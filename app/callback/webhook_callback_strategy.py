import hashlib
import json
from hmac import HMAC
from urllib.parse import urlencode
from uuid import UUID

from flask import current_app
from requests.api import request
from requests.exceptions import HTTPError, RequestException

from app import encryption, statsd_client
from app.callback.service_callback_strategy_interface import ServiceCallbackStrategyInterface
from app.celery.exceptions import NonRetryableException, RetryableException
from app.constants import HTTP_TIMEOUT
from app.dao.api_key_dao import get_unsigned_secret
from app.models import DeliveryStatusCallbackApiData


class WebhookCallbackStrategy(ServiceCallbackStrategyInterface):
    @staticmethod
    def send_callback(
        callback: DeliveryStatusCallbackApiData,
        payload: dict,
        logging_tags: dict,
    ) -> None:
        tags = ', '.join([f'{key}: {value}' for key, value in logging_tags.items()])
        try:
            response = request(
                method='POST',
                url=callback.url,
                data=json.dumps(payload),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {encryption.decrypt(callback._bearer_token)}',
                },
                timeout=HTTP_TIMEOUT,
            )
            current_app.logger.info('Callback sent to %s, response %d, %s', callback.url, response.status_code, tags)
            response.raise_for_status()

        except RequestException as e:
            if not isinstance(e, HTTPError) or e.response.status_code >= 500:
                statsd_client.incr(f'callback.webhook.{callback.callback_type}.retryable_error')
                raise RetryableException(e)
            else:
                statsd_client.incr(f'callback.webhook.{callback.callback_type}.non_retryable_error')
                raise NonRetryableException(e)
        else:
            statsd_client.incr(f'callback.webhook.{callback.callback_type}.success')


def generate_callback_signature(
    api_key_id: UUID,
    callback_params: dict[str, str],
) -> str:
    """Generate a signature based on key and params

    Args:
        api_key_id (UUID): ID of the key to generate the signature
        callback_params (dict[str, str]): Parameters being sent to the client

    Returns:
        str: The signature for this callback
    """
    signature = HMAC(
        get_unsigned_secret(api_key_id).encode(),
        urlencode(callback_params).encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    current_app.logger.debug('Generated signature: %s with params: %s', signature, callback_params)
    return signature
