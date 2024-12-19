from datetime import datetime, timezone
from uuid import UUID

from flask import current_app

from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.dao.notifications_dao import get_notification_by_id, update_notification_status_by_id
from app.constants import NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE


def can_retry(
    retries: int,
    max_retries: int,
    notification_id: UUID,
) -> bool:
    """Facilitates testing - Compares retries vs max retries returns True if retries < max_retries"""
    current_app.logger.info('Notification id: %s, max retries: %s, retries: %s', notification_id, max_retries, retries)
    return retries < max_retries


def handle_max_retries_exceeded(
    notification_id: str,
    method_name: str,
) -> str:
    """
    Handles sms/email deliver requests that exceeded the retry maximum.  Updates the Notification status.
    """

    current_app.logger.critical('%s: Notification %s failed by exceeding retry limits', method_name, notification_id)
    message = (
        'RETRY FAILED: Max retries reached. '
        f'The task {method_name} failed for notification {notification_id}. '
        'Notification has been updated to permanent-failure'
    )
    update_notification_status_by_id(
        notification_id,
        NOTIFICATION_PERMANENT_FAILURE,
        status_reason=STATUS_REASON_UNDELIVERABLE,
    )
    return message


def log_and_update_critical_failure(
    notification_id: UUID,
    method_name: str,
    e: Exception,
    status_reason: str,
) -> None:
    """Handles sms/email deliver requests that failed in a technical manner due to an exception."""
    current_app.logger.critical(
        '%s: Notification: %s - Experienced a critical failure with exception: %s',
        method_name,
        notification_id,
        e,
    )

    update_notification_status_by_id(
        notification_id,
        NOTIFICATION_PERMANENT_FAILURE,
        status_reason=status_reason,
    )

    current_app.logger.critical(
        'Notification %s encountered a technical exception and has been updated to a permanent-failure',
        notification_id,
    )

    notification = get_notification_by_id(notification_id)
    check_and_queue_callback_task(notification)


def log_and_update_permanent_failure(
    notification_id: UUID,
    method_name: str,
    e: Exception,
    status_reason: str,
) -> None:
    """Handles sms/email deliver requests that failed in a permanent manner due to an exception"""
    current_app.logger.warning(
        '%s: Notification: %s encountered a permanent exception: %s',
        method_name,
        notification_id,
        e,
    )
    update_notification_status_by_id(notification_id, NOTIFICATION_PERMANENT_FAILURE, status_reason=status_reason)
    current_app.logger.warning(
        'Notification: %s has been updated to a permanent-failure with status_reason: %s',
        notification_id,
        status_reason,
    )

    notification = get_notification_by_id(notification_id)
    check_and_queue_callback_task(notification)


def log_notification_total_time(
    notification_id: UUID,
    start_time: datetime,
    status: str,
    provider: str,
    event_timestamp: datetime | None = None,
) -> None:
    """Logs how long it took a notification to go from created to delivered"""
    if status == NOTIFICATION_DELIVERED:
        end_time = event_timestamp or datetime.now(timezone.utc).replace(tzinfo=None)
        total_time = (end_time - start_time).total_seconds()

        # Twilio RawDlrDoneDate can make this negative
        # https://www.twilio.com/en-us/changelog/addition-of-rawdlrdonedate-to-delivered-and-undelivered-status-webhooks
        corrected_total_time = (
            total_time
            if total_time > 0.0
            else (datetime.now(timezone.utc).replace(tzinfo=None) - start_time).total_seconds()
        )
        current_app.logger.info(
            'notification %s took %ss total time to reach %s status - %s',
            notification_id,
            corrected_total_time,
            status,
            provider,
        )
