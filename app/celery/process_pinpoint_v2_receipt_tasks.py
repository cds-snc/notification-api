from flask import current_app
from notifications_utils.statsd_decorators import statsd

from app import notify_celery
from app.celery.exceptions import AutoRetryException
from app.clients.sms import SmsStatusRecord
from app.celery.process_delivery_status_result_tasks import (
    sms_attempt_retry,
    sms_status_update,
)
from app.constants import CELERY_RETRY_BACKOFF_MAX, STATUS_REASON_RETRYABLE


@notify_celery.task(
    bind=True,
    name='process-pinpoint-v2-result',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=585,
    retry_backoff=True,
    retry_backoff_max=CELERY_RETRY_BACKOFF_MAX,
)
@statsd(namespace='tasks')
def process_pinpoint_v2_receipt_results(
    self,
    sms_status_record: SmsStatusRecord,
    event_timestamp: str,
) -> None:
    """
    Process a Pinpoint Voice SMS V2 SMS stream event.  Messages long enough to require multiple segments only
    result in one event that contains the aggregate cost.

    Permissible event type and message status values are documented here:
        https://docs.aws.amazon.com/sms-voice/latest/userguide/configuration-sets-event-types.html
    """

    current_app.logger.info(
        'Processing Pinpoint Incoming SMS Voice V2 result. | reference: %s | status: %s | status_reason: %s | '
        'message_parts: %s | price_millicents: %s | provider_updated_at: %s',
        sms_status_record.reference,
        sms_status_record.status,
        sms_status_record.status_reason,
        sms_status_record.message_parts,
        sms_status_record.price_millicents,
        sms_status_record.provider_updated_at,
    )

    if sms_status_record.status_reason == STATUS_REASON_RETRYABLE:
        sms_attempt_retry(sms_status_record, event_timestamp)
    else:
        sms_status_update(sms_status_record, event_timestamp)
