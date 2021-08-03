from botocore.exceptions import ClientError

from app import sqs_client
from app.callback.service_callback_strategy_interface import ServiceCallbackStrategyInterface

from flask import current_app

from app.celery.exceptions import NonRetryableException
from app.models import ServiceCallback


class QueueCallbackStrategy(ServiceCallbackStrategyInterface):
    @staticmethod
    def send_callback(callback: ServiceCallback, payload: dict, logging_tags: dict) -> None:
        tags = ', '.join([f"{key}: {value}" for key, value in logging_tags.items()])

        try:
            sqs_client.send_message(
                url=callback.url,
                payload=payload,
                message_attributes={"callback_type": {"StringValue": callback.callback_type, "DataType": "String"}}
            )
            current_app.logger.info(f"Callback sent to {callback.url}, {tags}")
        except ClientError as e:
            raise NonRetryableException(e)
