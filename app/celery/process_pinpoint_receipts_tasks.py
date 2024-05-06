from datetime import datetime
from typing import Union

from flask import current_app, json
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound

from app import notify_celery, statsd_client
from app.config import QueueNames
from app.dao import notifications_dao
from app.models import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    PINPOINT_PROVIDER,
)
from app.notifications.callbacks import _check_and_queue_callback_task
from celery.exceptions import Retry

# Pinpoint receipts are of the form:
#     {
#         "eventType": "TEXT_DELIVERED",
#         "eventVersion": "1.0",
#         "eventTimestamp": 1712944268877,
#         "isFinal": true,
#         "originationPhoneNumber": "+13655550100",
#         "destinationPhoneNumber": "+16135550123",
#         "isoCountryCode": "CA",
#         "mcc": "302",
#         "mnc": "610",
#         "carrierName": "Bell Cellular Inc. / Aliant Telecom",
#         "messageId": "221bc70c-7ee6-4987-b1ba-9684ba25be20",
#         "messageRequestTimestamp": 1712944267685,
#         "messageEncoding": "GSM",
#         "messageType": "TRANSACTIONAL",
#         "messageStatus": "DELIVERED",
#         "messageStatusDescription": "Message has been accepted by phone",
#         "totalMessageParts": 1,
#         "totalMessagePrice": 0.00581,
#         "totalCarrierFee": 0.006
#     }


@notify_celery.task(bind=True, name="process-pinpoint-result", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def process_pinpoint_results(self, response):
    try:
        receipt = json.loads(response["Message"])
        reference = receipt["messageId"]
        status = receipt["messageStatus"]
        provider_response = receipt["messageStatusDescription"]

        notification_status = determine_pinpoint_status(status, provider_response)
        if not notification_status:
            current_app.logger.warning(f"unhandled provider response for reference {reference}, received '{provider_response}'")
            notification_status = NOTIFICATION_TECHNICAL_FAILURE  # revert to tech failure by default

        try:
            notification = notifications_dao.dao_get_notification_by_reference(reference)
        except NoResultFound:
            try:
                current_app.logger.warning(
                    f"RETRY {self.request.retries}: notification not found for Pinpoint reference {reference} (update to {notification_status}). "
                    f"Callback may have arrived before notification was persisted to the DB. Adding task to retry queue"
                )
                self.retry(queue=QueueNames.RETRY)
            except self.MaxRetriesExceededError:
                current_app.logger.warning(
                    f"notification not found for Pinpoint reference: {reference} (update to {notification_status}). Giving up."
                )
            return
        if notification.sent_by != PINPOINT_PROVIDER:
            current_app.logger.exception(f"Pinpoint callback handled notification {notification.id} not sent by Pinpoint")
            return

        if notification.status != NOTIFICATION_SENT:
            notifications_dao._duplicate_update_warning(notification, notification_status)
            return

        notifications_dao._update_notification_status(
            notification=notification,
            status=notification_status,
            provider_response=provider_response,
        )

        if notification_status != NOTIFICATION_DELIVERED:
            current_app.logger.info(
                (
                    f"Pinpoint delivery failed: notification id {notification.id} and reference {reference} has error found. "
                    f"Provider response: {provider_response}"
                )
            )
        else:
            current_app.logger.info(
                f"Pinpoint callback return status of {notification_status} for notification: {notification.id}"
            )

        statsd_client.incr(f"callback.pinpoint.{notification_status}")

        if notification.sent_at:
            statsd_client.timing_with_dates("callback.pinpoint.elapsed-time", datetime.utcnow(), notification.sent_at)

        _check_and_queue_callback_task(notification)

        return True

    except Retry:
        raise

    except Exception as e:
        current_app.logger.exception(f"Error processing Pinpoint results: {str(e)}")
        self.retry(queue=QueueNames.RETRY)

    return


def determine_pinpoint_status(status: str, provider_response: str) -> Union[str, None]:
    """Determine the notification status based on the SMS status and provider response.

    Args:
        status (str): message status from AWS
        provider_response (str): detailed status from the SMS provider

    Returns:
        Union[str, None]: the notification status or None if the status is not handled
    """

    if status == "DELIVERED":
        return NOTIFICATION_DELIVERED

    response_lower = provider_response.lower()
    match response_lower:
        case response_lower if "blocked" in response_lower:
            return NOTIFICATION_TECHNICAL_FAILURE
        case response_lower if "invalid" in response_lower:
            return NOTIFICATION_TECHNICAL_FAILURE
        case response_lower if "is opted out" in response_lower:
            return NOTIFICATION_PERMANENT_FAILURE
        case response_lower if "unknown error" in response_lower:
            return NOTIFICATION_TECHNICAL_FAILURE
        case response_lower if "exceed max price" in response_lower:
            return NOTIFICATION_TECHNICAL_FAILURE
        case "phone carrier is currently unreachable/unavailable":
            return NOTIFICATION_TEMPORARY_FAILURE
        case "phone is currently unreachable/unavailable":
            return NOTIFICATION_PERMANENT_FAILURE

    return None
