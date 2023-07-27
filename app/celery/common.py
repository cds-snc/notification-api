from app.dao.notifications_dao import update_notification_status_by_id
from app.models import NOTIFICATION_TECHNICAL_FAILURE
from flask import current_app


RETRIES_EXCEEDED = "Retries exceeded"


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
