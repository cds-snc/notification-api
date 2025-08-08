import base64
import json

from flask import current_app
from notifications_utils.statsd_decorators import statsd

from app import aws_pinpoint_client, notify_celery, statsd_client
from app.celery.exceptions import AutoRetryException, NonRetryableException
from app.clients.sms import SmsStatusRecord, UNABLE_TO_TRANSLATE
from app.celery.process_delivery_status_result_tasks import (
    sms_attempt_retry,
    sms_status_update,
    get_notification_platform_status,
)
from app.constants import CELERY_RETRY_BACKOFF_MAX, STATUS_REASON_RETRYABLE


@notify_celery.task(
    bind=True,
    name='process-pinpoint-result',
    throws=(AutoRetryException,),
    autoretry_for=(AutoRetryException,),
    max_retries=585,
    retry_backoff=True,
    retry_backoff_max=CELERY_RETRY_BACKOFF_MAX,
)
@statsd(namespace='tasks')
def process_pinpoint_results(
    self,
    response,
) -> None:
    """
    Process a Pinpoint SMS stream event.  Messages long enough to require multiple segments only
    result in one event that contains the aggregate cost.

    Permissible event type and record status values are documented here:
        https://docs.aws.amazon.com/pinpoint/latest/developerguide/event-streams-data-sms.html

    An _SMS.OPTOUT event occurs when a veteran replies "STOP" to a text message.  An OPTED_OUT status occurs
    when Pinpoint receives input from Notify, but the Veteran has opted-out at the Pinpoint level.  This is
    different than Notify's communication item preferences.  If a veteran opts-out at that level, Pinpoint
    should never receive input trying to send a message to the opted-out veteran.
    """
    current_app.logger.debug('pinpoint incoming sms update: %s', response)

    try:
        pinpoint_message = json.loads(base64.b64decode(response['Message']))
        current_app.logger.debug('pinpoint decoded sms update: %s', pinpoint_message)
        event_type = pinpoint_message['event_type']
        record_status = pinpoint_message['attributes']['record_status']
    except (json.decoder.JSONDecodeError, ValueError, TypeError, KeyError) as e:
        current_app.logger.exception('Unable to decode the incoming pinpoint message')
        statsd_client.incr('clients.sms.pinpoint.status_update.error')
        raise NonRetryableException(f'Found {type(e).__name__}, {UNABLE_TO_TRANSLATE}')

    notification_platform_status: SmsStatusRecord = get_notification_platform_status(
        aws_pinpoint_client, pinpoint_message
    )

    current_app.logger.info(
        'Processing pinpoint result. | reference: %s | event_type: %s | record_status: %s | '
        'message_parts: %s | price_millicents: %s | provider_updated_at: %s',
        notification_platform_status.reference,
        event_type,
        record_status,
        notification_platform_status.message_parts,
        notification_platform_status.price_millicents,
        notification_platform_status.provider_updated_at,
    )

    if notification_platform_status.status_reason == STATUS_REASON_RETRYABLE:
        sms_attempt_retry(notification_platform_status, pinpoint_message['event_timestamp'])
    else:
        sms_status_update(notification_platform_status, pinpoint_message['event_timestamp'])
