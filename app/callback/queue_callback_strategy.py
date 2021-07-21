import json

from app import sqs_client
from app.callback.service_callback_strategy_interface import ServiceCallbackStrategyInterface

from flask import current_app


class QueueCallbackStrategy(ServiceCallbackStrategyInterface):
    @staticmethod
    def send_callback(self, payload: dict, url: str, logging_tags: dict, token: str = None) -> None:
        tags = ', '.join([f"{key}: {value}" for key, value in logging_tags.items()])
        response = sqs_client.send_message(json.dumps(payload))

        current_app.logger.info(f"{self.name} sent to {url}, response {response.status_code}, {tags}")
        response.raise_for_status()
