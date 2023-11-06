from app.config import QueueNames
from app.models import BULK, NORMAL, PRIORITY, SMS_TYPE
from flask import current_app
from typing import Any, Dict

# Default retry periods for sending notifications.
RETRY_DEFAULT = 300
RETRY_HIGH = 25

RETRY_PERIODS = {
    BULK: RETRY_DEFAULT,
    NORMAL: RETRY_DEFAULT,
    PRIORITY: RETRY_HIGH,
}


def build_retry_task_params(notification_type: str, notification_process_type: str) -> Dict[str, Any]:
    """
    Build task params for the sending parameter retry tasks.

    If the notification is a high priority SMS, set the retry policy to retry every 25 seconds
    else fall back to the default retry policy of retrying every 5 minutes.
    """
    params: dict[str, Any] = {"queue": QueueNames.RETRY}
    if current_app.config["FF_CELERY_CUSTOM_TASK_PARAMS"] is False:
        return params

    # Overring the retry policy is only supported for SMS for now;
    # email support coming later.
    if notification_type == SMS_TYPE:
        params["countdown"] = RETRY_PERIODS[notification_process_type]
    else:
        params["countdown"] = RETRY_DEFAULT
    return params
