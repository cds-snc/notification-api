from app.dao.notifications_dao import update_notification_status_by_id
from app.models import NOTIFICATION_TECHNICAL_FAILURE
from flask import current_app


RETRIES_EXCEEDED = "Retries exceeded"
TECHNICAL_ERROR = "VA Notify non-retryable technical error"


def can_retry(retries: int, max_retries: int, notification_id: str) -> bool:
    """ Facilitates testing - Compares retries vs max retries returns True if retries < max_retries """
    current_app.logger.info("Notification id: %s, max retries: %s, retries: %s", notification_id, max_retries, retries)
    return retries < max_retries


def handle_max_retries_exceeded(notification_id: str, method_name: str) -> str:
    """ Handles sms/email deliver requests that exceeded the retry maximum, updates Notification status """
    current_app.logger.critical("%s: Notification %s failed by exceeding retry limits", method_name, notification_id)
    message = ("RETRY FAILED: Max retries reached. "
               f"The task {method_name} failed for notification {notification_id}. "
               "Notification has been updated to technical-failure")
    update_notification_status_by_id(
        notification_id,
        NOTIFICATION_TECHNICAL_FAILURE,
        status_reason=RETRIES_EXCEEDED
    )
    return message


def handle_non_retryable(notification_id: str, method_name: str) -> str:
    """ Handles sms/email deliver requests that failed in a non-retryable manner """
    current_app.logger.critical("%s: Notification %s encountered a non-retryable exception",
                                method_name, notification_id)
    message = "Notification has been updated to technical-failure due to a non-retryable exception"
    update_notification_status_by_id(
        notification_id,
        NOTIFICATION_TECHNICAL_FAILURE,
        status_reason=TECHNICAL_ERROR
    )
    return message
