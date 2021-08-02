import json

from app import sqs_client
from app.callback.service_callback_strategy_interface import ServiceCallbackStrategyInterface

from flask import current_app

from app.models import ServiceCallback


class QueueCallbackStrategy(ServiceCallbackStrategyInterface):
    @staticmethod
    def send_callback(callback: ServiceCallback, payload: dict, logging_tags: dict) -> None:
        tags = ', '.join([f"{key}: {value}" for key, value in logging_tags.items()])
        response = sqs_client.send_message(json.dumps(payload))
        current_app.logger.info(f"Callback sent to {callback.url}, response {response.status_code}, {tags}")
        response.raise_for_status()
        return response
