from celery import Task

from app.callback.service_callback_strategy_interface import ServiceCallbackStrategyInterface

import json

from flask import current_app

from requests.api import request
from requests.exceptions import RequestException, HTTPError

from app.celery.exceptions import RetryableException, NonRetryableException
from app.models import ServiceCallback


class NotRetryableException(object):
    pass


class WebhookCallbackStrategy(ServiceCallbackStrategyInterface):
    @staticmethod
    def send_callback(task: Task, callback: ServiceCallback, payload: dict, logging_tags: dict) -> None:
        tags = ', '.join([f"{key}: {value}" for key, value in logging_tags.items()])
        try:
            response = request(
                method="POST",
                url=callback.url,
                data=json.dumps(payload),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer {}'.format(callback.bearer_token)
                },
                timeout=60
            )
            current_app.logger.info(f"{task.name} sent to {callback.url}, response {response.status_code}, {tags}")
            response.raise_for_status()

        except RequestException as e:
            if not isinstance(e, HTTPError) or e.response.status_code >= 500:
                raise RetryableException(e)
            else:
                raise NonRetryableException(e)
