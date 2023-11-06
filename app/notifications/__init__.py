from app.config import QueueNames
from app.models import BULK, NORMAL, PRIORITY, SMS_TYPE
from flask import current_app
from typing import Any, Dict

# Default retry policy for all notifications.
RETRY_POLICY_DEFAULT = {
    "max_retries": 48,
    "interval_start": 300,
    "interval_step": 300,
    "interval_max": 300,
    "retry_errors": None,
}

# Retry policy for high priority notifications.
RETRY_POLICY_HIGH = {
    "max_retries": 48,
    "interval_start": 25,
    "interval_step": 25,
    "interval_max": 25,
    "retry_errors": None,
}

# Retry policies for each notification priority lanes.
RETRY_POLICIES = {
    BULK: RETRY_POLICY_DEFAULT,
    NORMAL: RETRY_POLICY_DEFAULT,
    PRIORITY: RETRY_POLICY_HIGH,
}


def build_delivery_task_params(notification_type: str, notification_process_type: str) -> Dict[str, Any]:
    """
    Build task params for the sending parameter tasks.

    If the notification is a high priority SMS, set the retry policy to retry every 25 seconds
    else fall back to the default retry policy of retrying every 5 minutes.
    """
    if current_app.config["FF_CELERY_CUSTOM_TASK_PARAMS"] is False:
        return {}

    params: dict[str, Any] = {}
    params["retry"] = True
    # Overring the retry policy is only supported for SMS for now;
    # email support coming later.
    if notification_type == SMS_TYPE:
        params["retry_policy"] = RETRY_POLICIES[notification_process_type]
    else:
        params["retry_policy"] = RETRY_POLICY_DEFAULT
    return params


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
        params["countdown"] = RETRY_POLICIES[notification_process_type]["interval_step"]
    else:
        params["countdown"] = RETRY_POLICY_DEFAULT["interval_step"]
    return params
