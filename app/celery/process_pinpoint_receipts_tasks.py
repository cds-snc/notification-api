from datetime import datetime, timezone
from typing import Union

from flask import current_app, json
from notifications_utils.statsd_decorators import statsd
from notifications_utils.timezones import convert_utc_to_local_timezone
from sqlalchemy.orm.exc import NoResultFound

from app import annual_limit_client, notify_celery, statsd_client
from app.config import QueueNames
from app.dao import notifications_dao
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_for_service_for_day,
)
from app.models import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    PINPOINT_PROVIDER,
)
from app.notifications.callbacks import _check_and_queue_callback_task
from app.utils import prepare_notification_counts_for_seeding
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


# TODO FF_ANNUAL_LIMIT removal: Temporarily ignore complexity
# flake8: noqa: C901
@notify_celery.task(bind=True, name="process-pinpoint-result", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def process_pinpoint_results(self, response):
    try:
        receipt = json.loads(response["Message"])
        reference = receipt["messageId"]
        status = receipt["messageStatus"]
        provider_response = receipt["messageStatusDescription"]
        isFinal = receipt["isFinal"]

        # some of these fields might be missing in the receipt
        total_message_price = receipt.get("totalMessagePrice")
        total_carrier_fee = receipt.get("totalCarrierFee")
        iso_country_code = receipt.get("isoCountryCode")
        carrier_name = receipt.get("carrierName")
        message_encoding = receipt.get("messageEncoding")
        origination_phone_number = receipt.get("originationPhoneNumber")

        notification_status = determine_pinpoint_status(status, provider_response, isFinal)

        if notification_status == NOTIFICATION_SENT:
            return  # we don't want to update the status to sent if it's already sent

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
            sms_total_message_price=total_message_price,
            sms_total_carrier_fee=total_carrier_fee,
            sms_iso_country_code=iso_country_code,
            sms_carrier_name=carrier_name,
            sms_message_encoding=message_encoding,
            sms_origination_phone_number=origination_phone_number,
        )

        service_id = notification.service_id
        # Flags if seeding has occurred. Since we seed after updating the notification status in the DB then the current notification
        # is included in the fetch_notification_status_for_service_for_day call below, thus we don't need to increment the count.
        notifications_to_seed = None

        if current_app.config["FF_ANNUAL_LIMIT"]:
            if not annual_limit_client.was_seeded_today(service_id):
                annual_limit_client.set_seeded_at(service_id)
                notifications_to_seed = fetch_notification_status_for_service_for_day(
                    datetime.now(timezone.utc),
                    service_id=service_id,
                )
                annual_limit_client.seed_annual_limit_notifications(
                    service_id, prepare_notification_counts_for_seeding(notifications_to_seed)
                )

        if notification_status != NOTIFICATION_DELIVERED:
            current_app.logger.info(
                (
                    f"Pinpoint delivery failed: notification id {notification.id} and reference {reference} has error found. "
                    f"Provider response: {provider_response}"
                )
            )
            # TODO FF_ANNUAL_LIMIT removal
            if current_app.config["FF_ANNUAL_LIMIT"]:
                # Only increment if we didn't just seed.
                if notifications_to_seed is None:
                    annual_limit_client.increment_sms_failed(service_id)
                current_app.logger.info(
                    f"Incremented sms_delivered count in Redis. Service: {service_id} Notification: {notification.id} Current counts: {annual_limit_client.get_all_notification_counts(service_id)}"
                )
        else:
            current_app.logger.info(
                f"Pinpoint callback return status of {notification_status} for notification: {notification.id}"
            )

            # TODO FF_ANNUAL_LIMIT removal
            if current_app.config["FF_ANNUAL_LIMIT"]:
                # Only increment if we didn't just seed.
                if notifications_to_seed is None:
                    annual_limit_client.increment_sms_delivered(service_id)
                current_app.logger.info(
                    f"Incremented sms_delivered count in Redis. Service: {service_id} Notification: {notification.id} Current counts: {annual_limit_client.get_all_notification_counts(service_id)}"
                )

        statsd_client.incr(f"callback.pinpoint.{notification_status}")

        if notification.sent_at:
            statsd_client.timing_with_dates(
                "callback.pinpoint.elapsed-time",
                datetime.utcnow(),
                notification.sent_at,
            )

        _check_and_queue_callback_task(notification)

    except Retry:
        raise

    except Exception as e:
        current_app.logger.exception(f"Error processing Pinpoint results: {str(e)}")
        self.retry(queue=QueueNames.RETRY)


def determine_pinpoint_status(status: str, provider_response: str, isFinal: bool) -> Union[str, None]:
    """Determine the notification status based on the SMS status and provider response.

    Args:
        status (str): message status from AWS
        provider_response (str): detailed status from the SMS provider
        isFinal (bool): whether this is the last update for this send

    Returns:
        Union[str, None]: the notification status or None if the status is not handled
    """

    if status == "DELIVERED" or status == "SUCCESSFUL" and isFinal:
        return NOTIFICATION_DELIVERED
    elif status == "SUCCESSFUL":  # carrier has accepted the message but it hasn't gone to the phone yet
        return NOTIFICATION_SENT

    response_lower = provider_response.lower()

    if "blocked" in response_lower:
        return NOTIFICATION_TECHNICAL_FAILURE
    elif "invalid" in response_lower:
        return NOTIFICATION_TECHNICAL_FAILURE
    elif "is opted out" in response_lower:
        return NOTIFICATION_PERMANENT_FAILURE
    elif "unknown error" in response_lower:
        return NOTIFICATION_TECHNICAL_FAILURE
    elif "exceed max price" in response_lower:
        return NOTIFICATION_TECHNICAL_FAILURE
    elif "phone carrier is currently unreachable/unavailable" in response_lower:
        return NOTIFICATION_TEMPORARY_FAILURE
    elif "phone is currently unreachable/unavailable" in response_lower:
        return NOTIFICATION_PERMANENT_FAILURE
    else:
        return None
