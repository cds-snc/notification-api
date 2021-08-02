import json

from app import sqs_client
from app.callback.service_callback_strategy_interface import ServiceCallbackStrategyInterface

from flask import current_app

from app.models import ServiceCallback


class QueueCallbackStrategy(ServiceCallbackStrategyInterface):
    @staticmethod
    def send_callback(callback: ServiceCallback, payload: dict, logging_tags: dict) -> None:
        tags = ', '.join([f"{key}: {value}" for key, value in logging_tags.items()])
        sqs_client.send_message(
            url=callback.url,
            payload=json.dumps(payload),
            message_attributes={"callback_type": {"StringValue": callback.callback_type, "DataType": "String"}}
        )

        current_app.logger.info(f"Callback sent to {callback.url}, {tags}")
