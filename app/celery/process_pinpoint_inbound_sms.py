import json
from datetime import datetime

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from typing_extensions import TypedDict

from app import notify_celery, statsd_client
from app.celery.service_callback_tasks import send_inbound_sms_to_service
from app.config import QueueNames
from app.feature_flags import FeatureFlag, is_feature_enabled
from app.notifications.receive_notifications import fetch_potential_service, create_inbound_sms_object


class PinpointInboundSmsMessage(TypedDict):
    messageBody: str
    destinationNumber: str
    originationNumber: str
    inboundMessageId: str


class CeleryEvent(TypedDict):
    Message: str


@notify_celery.task(bind=True, name='process-pinpoint-inbound-sms', max_retries=5, default_retry_delay=300)
@statsd(namespace='tasks')
def process_pinpoint_inbound_sms(
    self,
    event: CeleryEvent,
):
    provider_name = 'pinpoint'

    if not is_feature_enabled(FeatureFlag.PINPOINT_INBOUND_SMS_ENABLED):
        current_app.logger.info('Pinpoint inbound SMS toggle is disabled, skipping task')
        return True

    pinpoint_message: PinpointInboundSmsMessage = json.loads(event['Message'])

    service = fetch_potential_service(pinpoint_message['destinationNumber'], provider_name)

    statsd_client.incr(f'inbound.{provider_name}.successful')

    inbound_sms = create_inbound_sms_object(
        service=service,
        content=pinpoint_message['messageBody'],
        notify_number=pinpoint_message['destinationNumber'],
        from_number=pinpoint_message['originationNumber'],
        provider_ref=pinpoint_message['inboundMessageId'],
        date_received=datetime.utcnow(),
        provider_name=provider_name,
    )

    send_inbound_sms_to_service.apply_async([inbound_sms.id, service.id], queue=QueueNames.NOTIFY)
