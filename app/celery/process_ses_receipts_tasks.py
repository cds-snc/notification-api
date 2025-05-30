import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TypedDict, cast

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound

from app import annual_limit_client, bounce_rate_client, notify_celery, statsd_client
from app.annual_limit_utils import get_annual_limit_notifications_v3
from app.config import QueueNames
from app.dao import notifications_dao
from app.models import NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE, Notification
from app.notifications.callbacks import _check_and_queue_callback_task
from app.notifications.notifications_ses_callback import (
    _check_and_queue_complaint_callback_task,
    get_aws_responses,
    handle_complaint,
)
from celery.exceptions import Retry


class SESMailHeader(TypedDict):
    name: str
    value: str


class SESMailCommonHeaders(TypedDict, total=False):
    # 'from' is a reserved word, so use 'from_' and map as needed in code
    from_: List[str]  # maps to 'from' in JSON
    to: List[str]
    messageId: str
    subject: str


class SESMail(TypedDict, total=False):
    timestamp: str
    source: str
    sourceArn: str
    sourceIp: str
    callerIdentity: str
    sendingAccountId: str
    messageId: str
    destination: List[str]
    headersTruncated: bool
    headers: List[SESMailHeader]
    commonHeaders: SESMailCommonHeaders
    tags: Dict[str, List[str]]


class SESDelivery(TypedDict, total=False):
    """Structure of the 'delivery' field in SES delivery notification receipts"""

    timestamp: str
    processingTimeMillis: int
    recipients: List[str]
    smtpResponse: str
    remoteMtaIp: str
    reportingMTA: str


class SESBounce(TypedDict, total=False):
    """Structure of the 'bounce' field in SES bounce notification receipts"""

    bounceType: str
    bounceSubType: str
    bouncedRecipients: List[Dict[str, str]]
    timestamp: str
    feedbackId: str


class SESComplaintRecipient(TypedDict):
    emailAddress: str


class SESComplaint(TypedDict, total=False):
    """Structure of the 'complaint' field in SES complaint notification receipts"""

    complainedRecipients: List[SESComplaintRecipient]
    timestamp: str
    feedbackId: str
    userAgent: str
    complaintFeedbackType: str
    arrivalDate: str
    complaintSubType: str


class SESReject(TypedDict, total=False):
    reason: str


class SESSend(TypedDict, total=False):
    # SES send record has no documented fields, but allow for extension
    pass


class SESReceipt(TypedDict, total=False):
    """Structure of SES notification receipts"""

    eventType: str  # e.g., "Complaint", "Delivery", "Send", "Reject"
    notificationType: str
    mail: SESMail
    delivery: Optional[SESDelivery]
    bounce: Optional[SESBounce]
    complaint: Optional[SESComplaint]
    reject: Optional[SESReject]
    send: Optional[SESSend]


def handle_complaints(receipts: List[SESReceipt]) -> List[SESReceipt]:
    """Processes the current batch of notification receipts. Handles complaints, removing them from the batch
       and returning the remaining messages for further processing.

    Args:
        messages (List[SESReceipt]): List of SES messages received from the SQS receipt buffer queue.

    Returns:
        Tuple[List[str], List[SESReceipt]]: A tuple containing a list of notification reference IDs and a reduced list of
        SES messages not containing any complaint receipts.
    """
    ref_ids = []
    complaint_free_messages = []
    current_app.logger.info(f"[batch-celery] - Received: {len(receipts)} receipts from Lambda.. beginning processing")

    for receipt, notification in receipts:
        notification_type = receipt["notificationType"]

        if notification_type == "Complaint":
            current_app.logger.info(f"[batch-celery] - Handling complaint: {receipt}")
            _check_and_queue_complaint_callback_task(*handle_complaint(receipt, notification))
        else:
            ref_ids.append(receipt["mail"]["messageId"])
            complaint_free_messages.append(receipt)

    current_app.logger.info(f"[batch-celery] - Complaints handled, processing: {len(complaint_free_messages)} remaining receipts")
    return complaint_free_messages


def fetch_notifications(ref_ids: List[str]) -> Optional[List[Notification]]:
    """Fetch notifications by reference IDs."""
    try:
        return notifications_dao.dao_get_notifications_by_references(ref_ids)
    except NoResultFound:
        return None
    except Exception as e:
        raise e


def categorize_receipts(
    ses_messages: List[SESReceipt], notifications: List[Notification]
) -> Tuple[List[Tuple[SESReceipt, Notification]], List[SESReceipt]]:
    """Categorize SES messages into those with and without notifications."""
    receipts_with_notification = []
    receipts_with_no_notification = []
    notification_map = {n.reference: n for n in notifications}

    for message in ses_messages:
        message_id = message["mail"]["messageId"]
        notification = notification_map.get(message_id)
        if notification:
            receipts_with_notification.append((message, notification))
        else:
            receipts_with_no_notification.append(message)

    return receipts_with_notification, receipts_with_no_notification


def process_notifications(
    receipts_with_notification: List[Tuple[SESReceipt, Notification]],
) -> List[Tuple[SESReceipt, Notification, Dict[str, Any]]]:
    """Process notifications and update their statuses."""
    updates = []
    receipts_with_notification_and_aws_response_dict = []

    for message, notification in receipts_with_notification:
        aws_response_dict = get_aws_responses(message)
        new_status = aws_response_dict["notification_status"]

        if not (notification.status == NOTIFICATION_PERMANENT_FAILURE and new_status == NOTIFICATION_DELIVERED):
            updates.append(
                {
                    "notification": notification,
                    "new_status": new_status,
                    "provider_response": aws_response_dict.get("provider_response"),
                    "bounce_response": aws_response_dict.get("bounce_response"),
                }
            )
        receipts_with_notification_and_aws_response_dict.append((message, notification, aws_response_dict))
        current_app.logger.info(f"[batch-celery] process_notifications - updates: {len(updates)}")

    notifications_dao._update_notification_statuses(updates)
    return receipts_with_notification_and_aws_response_dict


def update_annual_limit_and_bounce_rate(
    receipt: SESReceipt, notification: Notification, aws_response_dict: Dict[str, Any]
) -> None:
    new_status = aws_response_dict["notification_status"]
    is_success = aws_response_dict["success"]
    log_prefix = f"SES callback for notification {notification.id} reference {notification.reference} for service {notification.service_id}: "
    # Check if we have already seeded the annual limit counts for today, if we have we do not need to increment later on.
    # We seed AFTER updating the notification status, thus the current notification will already be counted.

    _, did_we_seed = get_annual_limit_notifications_v3(notification.service_id)
    current_app.logger.info(f"[alimit-debug] did_we_seed: {did_we_seed}, data: {_}")

    if not is_success:
        current_app.logger.info(f"{log_prefix} Delivery failed with error: {aws_response_dict["message"]}")

        if not did_we_seed:
            annual_limit_client.increment_email_failed(notification.service_id)
            current_app.logger.info(
                f"Incremented email_failed count in Redis. Service: {notification.service_id} Notification: {notification.id} Current counts: {annual_limit_client.get_all_notification_counts(notification.service_id)}"
            )
    else:
        current_app.logger.info(
            f"{log_prefix} Delivery status: {new_status}" "SES callback return status of {} for notification: {}".format(
                new_status, notification.id
            )
        )

        if not did_we_seed:
            annual_limit_client.increment_email_delivered(notification.service_id)
            current_app.logger.info(
                f"Incremented email_delivered count in Redis. Service: {notification.service_id} Notification: {notification.id} current counts: {annual_limit_client.get_all_notification_counts(notification.service_id)}"
            )

    statsd_client.incr("callback.ses.{}".format(new_status))

    if new_status == NOTIFICATION_PERMANENT_FAILURE:
        bounce_rate_client.set_sliding_hard_bounce(notification.service_id, str(notification.id))
        current_app.logger.info(
            f"Setting total hard bounce notifications for service {notification.service_id} with notification {notification.id} in REDIS"
        )

    if notification.sent_at:
        statsd_client.timing_with_dates("callback.ses.elapsed-time", datetime.utcnow(), notification.sent_at)


def handle_retries(self, receipts_with_no_notification: List[SESReceipt]) -> None:
    """Handle retries for receipts without notifications."""
    retry_ids = ", ".join([msg["mail"]["messageId"] for msg in receipts_with_no_notification])
    try:
        current_app.logger.warning(
            f"RETRY {self.request.retries}: notifications not found for SES references {retry_ids}. "
            f"Callback may have arrived before notification was persisted to the DB. Adding task to retry queue"
        )
        self.retry(queue=QueueNames.RETRY, args=[{"Messages": receipts_with_no_notification}])
    except self.MaxRetriesExceededError:
        current_app.logger.error(f"notifications not found for SES references: {retry_ids}. Giving up.")


@notify_celery.task(
    bind=True,
    name="process-ses-result",
    max_retries=5,
    default_retry_delay=300,
)
@statsd(namespace="tasks")
def process_ses_results(self, response: Dict[str, Any]) -> Optional[bool]:
    start_time = time.time()  # TODO : Remove after benchmarking
    receipts = cast(List[SESReceipt], response["Messages"] if "Messages" in response else [json.loads(response["Message"])])
    ref_ids = [receipt["mail"]["messageId"] for receipt in receipts]
    current_app.logger.info(f"[batch-celery] - Received response from lambda: {response}, total receipts: {len(receipts)}")

    try:
        notifications = fetch_notifications(ref_ids)

        # Retry if no notifications are in the DB yet
        if notifications is None:
            current_app.logger.info(
                f"[batch-celery] - No notifications found in the DB for reference ids: {", ".join(ref_ids)} Queuing {len(ref_ids)} receipts for retry"
            )
            handle_retries(self, receipts)
            return None

        # Categorize receipts into those with and without notifications
        receipts_with_notification, receipts_with_no_notification = categorize_receipts(
            cast(List[SESReceipt], receipts), notifications
        )
        current_app.logger.info(
            f"[batch-celery] - with notifications: {receipts_with_notification} No notifications: {receipts_with_no_notification}"
        )

        # Process complaints, finish early if all the receipts are complaints
        # TODO: Technically complaint handling could be parallelized with the non-complaint processing to
        # further optimize receipt processing, but as of 2025-05-30 & batch saving v1 this is not a priority.
        ses_messages = handle_complaints(receipts_with_notification)
        if not ses_messages:
            return True

        # Update the notification statuses in the DB
        receipts_with_notification_and_aws_response_dict = process_notifications(receipts_with_notification)
        current_app.logger.info(
            f"[batch-celery] - receipts_with_notification_and_aws_response_dict length: {len(receipts_with_notification_and_aws_response_dict)}"
        )

        # Update annual limits, bounce rates, and enqueue API callback tasks for successfully updated notifications
        for message, notification, aws_response_dict in receipts_with_notification_and_aws_response_dict:
            update_annual_limit_and_bounce_rate(message, notification, aws_response_dict)
            _check_and_queue_callback_task(notification)

        # Enqueue retry tasks for receipts that did not yet have a notification in the DB
        if receipts_with_no_notification:
            current_app.logger.info(f"[batch-celery] - Queuing {len(receipts_with_no_notification)} receipts for retry")
            handle_retries(self, receipts_with_no_notification)

        end_time = time.time()
        current_app.logger.info(f"[batch-celery] - process_ses_results took {end_time - start_time} seconds")
        return True

    except Retry:
        end_time = time.time()
        current_app.logger.info(f"[batch-celery] Retry - process_ses_results took {end_time - start_time} seconds")
        raise
    except Exception:
        current_app.logger.exception(f"Error processing SES results for receipt batch: {response['Messages']}")
        self.retry(queue=QueueNames.RETRY, args=[{"Messages": receipts}])
        return None
