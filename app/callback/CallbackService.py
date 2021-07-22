from app.callback.queue_callback_strategy import QueueCallbackStrategy
from app.callback.webhook_callback_strategy import WebhookCallbackStrategy
from app.models import WEBHOOK_CHANNEL_TYPE, QUEUE_CHANNEL_TYPE


class CallbackService:
    def __init__(self):
        self.callback_channels = {
            WEBHOOK_CHANNEL_TYPE: WebhookCallbackStrategy,
            QUEUE_CHANNEL_TYPE: QueueCallbackStrategy
        }

    def send_to_service_callback(self, callback_channel, payload, url, logging_tags, token):
        strategy = self.callback_channels[callback_channel]
        strategy.send_callback(payload, url, logging_tags, token)
