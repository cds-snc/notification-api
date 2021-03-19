import base64
from datetime import datetime
import json

from flask import current_app
from typing_extensions import TypedDict
from notifications_utils.statsd_decorators import statsd

from app import notify_celery
from app.config import QueueNames
from app.feature_flags import FeatureFlag, is_feature_enabled
from app.notifications.receive_notifications import fetch_potential_service, create_inbound_sms_object
from app.celery.tasks import send_inbound_sms_to_service


class PinpointInboundSmsMessage(TypedDict):
    messageBody: str
    destinationNumber: str
    originationNumber: str
    inboundMessageId: str


class CeleryEvent(TypedDict):
    Message: str


class NoSuitableServiceForInboundSms(Exception):
    pass


@notify_celery.task(bind=True, name='process-pinpoint-inbound-sms', max_retries=5, default_retry_delay=300)
@statsd(namespace='tasks')
def process_pinpoint_inbound_sms(self, event: CeleryEvent):
    provider_name = 'pinpoint'

    if not is_feature_enabled(FeatureFlag.PINPOINT_INBOUND_SMS_ENABLED):
        current_app.logger.info('Pinpoint inbound SMS toggle is disabled, skipping task')
        return True

    pinpoint_message: PinpointInboundSmsMessage = json.loads(base64.b64decode(event['Message']))

    service = fetch_potential_service(pinpoint_message['destinationNumber'], provider_name)
    if not service:
        raise NoSuitableServiceForInboundSms

    inbound_sms = create_inbound_sms_object(
        service=service,
        content=pinpoint_message['messageBody'],
        from_number=pinpoint_message['originationNumber'],
        provider_ref=pinpoint_message['inboundMessageId'],
        date_received=datetime.utcnow(),
        provider_name=provider_name
    )

    send_inbound_sms_to_service.apply_async([str(inbound_sms.id), str(service.id)], queue=QueueNames.NOTIFY)
