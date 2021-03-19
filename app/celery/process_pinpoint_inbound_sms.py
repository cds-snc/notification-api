import base64
import json

from flask import current_app
from typing_extensions import TypedDict
from notifications_utils.statsd_decorators import statsd

from app import notify_celery
from app.feature_flags import FeatureFlag, is_feature_enabled
from app.notifications.receive_notifications import fetch_potential_service


class PinpointInboundSmsMessage(TypedDict):
    messageBody: str
    destinationNumber: str
    originationNumber: str


class CeleryEvent(TypedDict):
    Message: str


class NoSuitableServiceForInboundSms(Exception):
    pass


@notify_celery.task(bind=True, name='process-pinpoint-inbound-sms', max_retries=5, default_retry_delay=300)
@statsd(namespace='tasks')
def process_pinpoint_inbound_sms(self, event: CeleryEvent):
    if not is_feature_enabled(FeatureFlag.PINPOINT_INBOUND_SMS_ENABLED):
        current_app.logger.info('Pinpoint inbound SMS toggle is disabled, skipping task')
        return True

    pinpoint_message: PinpointInboundSmsMessage = json.loads(base64.b64decode(event['Message']))

    service = fetch_potential_service(pinpoint_message['destinationNumber'], 'pinpoint')
    if not service:
        raise NoSuitableServiceForInboundSms
