from app.callback.service_callback_strategy_interface import ServiceCallbackStrategyInterface

import json

from flask import current_app

from requests.api import request
from requests.exceptions import RequestException, HTTPError
from app.config import QueueNames


class WebhookCallbackStrategy(ServiceCallbackStrategyInterface):
    @staticmethod
    def send_callback(self, payload: dict, url: str, logging_tags: dict, token: str) -> None:
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
            current_app.logger.info(f"{self.name} sent to {url}, response {response.status_code}, {tags}")
            response.raise_for_status()
        except RequestException as e:
            if not isinstance(e, HTTPError) or e.response.status_code >= 500:
                current_app.logger.warning(f"Retrying: {self.name} request failed for url: {url}. exc: {e}, {tags}")
                try:
                    self.retry(queue=QueueNames.RETRY)
                except self.MaxRetriesExceededError:
                    current_app.logger.error(
                        f"Retry: {self.name} has retried the max num of times for url {url}, {tags}")
            else:
                current_app.logger.error(f"Not retrying: {self.name} request failed for url: {url}. exc: {e}, {tags}")
