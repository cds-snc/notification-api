import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TypedDict, cast

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound

from app import annual_limit_client, bounce_rate_client, notify_celery, statsd_client
from app.annual_limit_utils import get_annual_limit_notifications_v2
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


class SESMail(TypedDict):
    """Structure of the 'mail' field in SES notification receipts"""

    timestamp: str
    source: str
    sourceArn: str
    sourceIp: str
    callerIdentity: str
    sendingAccountId: str
    messageId: str
    destination: List[str]


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


class SESComplaint(TypedDict, total=False):
    """Structure of the 'complaint' field in SES complaint notification receipts"""

    complainedRecipients: List[Dict[str, str]]
    timestamp: str
    feedbackId: str
    complaintSubType: str
    complaintFeedbackType: str


class SESReceipt(TypedDict):
    """Structure of SES notification receipts"""

    notificationType: str
    mail: SESMail
    delivery: Optional[SESDelivery]
    bounce: Optional[SESBounce]
    complaint: Optional[SESComplaint]


def handle_complaints_and_extract_ref_ids(messages: List[SESReceipt]) -> Tuple[List[str], List[SESReceipt]]:
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
    current_app.logger.info(f"[batch-celery] - Received: {len(messages)} receipts from Lambda.. beginning processing")
    for message in messages:
        notification_type = message["notificationType"]
        if notification_type == "Complaint":
            current_app.logger.info(f"[batch-celery] - Handling complaint: {message}")
            _check_and_queue_complaint_callback_task(*handle_complaint(message))
        else:
            ref_ids.append(message["mail"]["messageId"])
            complaint_free_messages.append(message)
    current_app.logger.info(f"[batch-celery] - Complaints handled, processing: {len(complaint_free_messages)} remaining receipts")
    return ref_ids, complaint_free_messages


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
    ff_annual_limit = current_app.config["FF_ANNUAL_LIMIT"]
    new_status = aws_response_dict["notification_status"]
    is_success = aws_response_dict["success"]
    log_prefix = f"SES callback for notification {notification.id} reference {notification.reference} for service {notification.service_id}: "
    # Check if we have already seeded the annual limit counts for today, if we have we do not need to increment later on.
    # We seed AFTER updating the notification status, thus the current notification will already be counted.
    if ff_annual_limit:
        seeded_today = None
        if not annual_limit_client.was_seeded_today(notification.service_id):
            seeded_today = get_annual_limit_notifications_v2(notification.service_id)

    if not is_success:
        current_app.logger.info(f"{log_prefix} Delivery failed with error: {aws_response_dict['message']}")

        if ff_annual_limit and not seeded_today:
            annual_limit_client.increment_email_failed(notification.service_id)
            current_app.logger.info(
                f"Incremented email_failed count in Redis. Service: {notification.service_id} Notification: {notification.id} Current counts: {annual_limit_client.get_all_notification_counts(notification.service_id)}"
            )
    else:
        current_app.logger.info(f"{log_prefix} Delivery status: {new_status}")

        if ff_annual_limit and not seeded_today:
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
        current_app.logger.warning(f"notifications not found for SES references: {retry_ids}. Giving up.")


@notify_celery.task(
    bind=True,
    name="process-ses-result",
    max_retries=5,
    default_retry_delay=300,
)
@statsd(namespace="tasks")
def process_ses_results(self, response: Dict[str, Any]) -> Optional[bool]:
    start_time = time.time()  # TODO : Remove after benchmarking
    receipts = response["Messages"] if "Messages" in response else [json.loads(response["Message"])]

    try:
        ref_ids, ses_messages = handle_complaints_and_extract_ref_ids(cast(List[SESReceipt], receipts))
        if not ses_messages:
            return True

        notifications = fetch_notifications(ref_ids)
        if notifications is None:
            handle_retries(self, ses_messages)
            return None

        receipts_with_notification, receipts_with_no_notification = categorize_receipts(ses_messages, notifications)
        receipts_with_notification_and_aws_response_dict = process_notifications(receipts_with_notification)

        for message, notification, aws_response_dict in receipts_with_notification_and_aws_response_dict:
            update_annual_limit_and_bounce_rate(message, notification, aws_response_dict)
            _check_and_queue_callback_task(notification)

        if receipts_with_no_notification:
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
