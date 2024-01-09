from app.callback.service_callback_strategy_interface import ServiceCallbackStrategyInterface

import json

from flask import current_app

from requests.api import request
from requests.exceptions import RequestException, HTTPError

from app import statsd_client
from app.celery.exceptions import RetryableException, NonRetryableException
from app.models import ServiceCallback


class WebhookCallbackStrategy(ServiceCallbackStrategyInterface):
    @staticmethod
    def send_callback(
        callback: ServiceCallback,
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
                    'Authorization': 'Bearer {}'.format(callback.bearer_token),
                },
                timeout=(3.05, 1),
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
