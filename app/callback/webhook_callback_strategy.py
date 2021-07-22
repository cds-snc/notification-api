from app.callback.service_callback_strategy_interface import ServiceCallbackStrategyInterface

import json

from flask import current_app, Response

from requests.api import request
from requests.exceptions import RequestException, HTTPError
from app.config import QueueNames


class WebhookCallbackStrategy(ServiceCallbackStrategyInterface):
    @staticmethod
    def send_callback(task, payload: dict, url: str, logging_tags: dict, token: str) -> Response:
        tags = ', '.join([f"{key}: {value}" for key, value in logging_tags.items()])
        try:
            response = request(
                method="POST",
                url=url,
                data=json.dumps(payload),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer {}'.format(token)
                },
                timeout=60
            )
            current_app.logger.info(f"{task.name} sent to {url}, response {response.status_code}, {tags}")
            response.raise_for_status()

            return response
        except RequestException as e:
            if not isinstance(e, HTTPError) or e.response.status_code >= 500:
                current_app.logger.warning(f"Retrying: {task.name} request failed for url: {url}. exc: {e}, {tags}")
                try:
                    task.retry(queue=QueueNames.RETRY)
                except task.MaxRetriesExceededError:
                    current_app.logger.error(
                        f"Retry: {task.name} has retried the max num of times for url {url}, {tags}")
            else:
                current_app.logger.error(f"Not retrying: {task.name} request failed for url: {url}. exc: {e}, {tags}")
