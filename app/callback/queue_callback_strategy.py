from botocore.exceptions import ClientError

from app import sqs_client
from app.callback.service_callback_strategy_interface import ServiceCallbackStrategyInterface

from flask import current_app

from app.celery.exceptions import NonRetryableException
from app.models import DeliveryStatusCallbackApiData
from app import statsd_client


class QueueCallbackStrategy(ServiceCallbackStrategyInterface):
    @staticmethod
    def send_callback(
        callback: DeliveryStatusCallbackApiData,
        payload: dict,
        logging_tags: dict,
    ) -> None:
        tags = ', '.join([f'{key}: {value}' for key, value in logging_tags.items()])

        try:
            sqs_client.send_message(
                url=callback.url,
                message_body=payload,
                message_attributes={'CallbackType': {'StringValue': callback.callback_type, 'DataType': 'String'}},
            )
        except ClientError as e:
            statsd_client.incr(f'callback.queue.{callback.callback_type}.non_retryable_error')
            raise NonRetryableException(e)

        current_app.logger.info('Callback sent to %s, %s', callback.url, tags)
        statsd_client.incr(f'callback.queue.{callback.callback_type}.success')
