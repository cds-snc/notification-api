"""
Celery error classification for CloudWatch alarm differentiation.

Known/expected errors are tagged with a category marker in the logs so that
the log filters can distinguish them from truly unexpected errors.
"""

from enum import Enum
from typing import Optional, Tuple


# The categories themselves are defined here, along with the logic to classify
# exceptions into categories. The actual logging of these classifications is
# performed by NotifyTask.on_failure in app/celery/celery.py to avoid coupling the
# error classification logic with the Celery app setup.
class CeleryErrorCategory(str, Enum):
    """Categories of Celery errors for log metric differentiation."""

    # Duplicate DB records in an idempotent system — generally safe to ignore
    DUPLICATE_RECORD = "CELERY_KNOWN_ERROR::DUPLICATE_RECORD"

    # Incomplete jobs due to deploys or other interruptions — don't ignore too much though
    JOB_INCOMPLETE = "CELERY_KNOWN_ERROR::JOB_INCOMPLETE"

    # Notification not found for SES references — safe to ignore, but should be investigated if it spikes
    NOTIFICATION_NOT_FOUND = "CELERY_KNOWN_ERROR::NOTIFICATION_NOT_FOUND"

    # Celery retry mechanism -- these errors are normal and used by Celery to retry a task
    TASK_RETRY = "CELERY_KNOWN_ERROR::TASK_RETRY"

    # Shutdown related errors — expected during deploys, safe to ignore
    SHUTDOWN = "CELERY_KNOWN_ERROR::SHUTDOWN"

    # Transient AWS errors — expected under load, retry will handle them
    THROTTLING = "CELERY_KNOWN_ERROR::THROTTLING"

    # Notifications that timed out
    TIMEOUT = "CELERY_KNOWN_ERROR::TIMEOUT"

    # Unknown / unclassified — these should trigger sensitive alarms
    UNKNOWN = "CELERY_UNKNOWN_ERROR"

    # Xray related errors
    XRAY = "CELERY_KNOWN_ERROR::XRAY"


# Map exception class names (or substrings in the message) to categories.
# Note: Order within the map does not matter; the deepest/root exception in the
# chain takes precedence over wrapper exceptions.
_EXCEPTION_CLASS_MAP: dict[str, CeleryErrorCategory] = {
    "UniqueViolation": CeleryErrorCategory.DUPLICATE_RECORD,
    "JobIncompleteError": CeleryErrorCategory.JOB_INCOMPLETE,
    "ThrottlingException": CeleryErrorCategory.THROTTLING,
    "TooManyRequestsException": CeleryErrorCategory.THROTTLING,
    "RequestLimitExceeded": CeleryErrorCategory.THROTTLING,
    "Retry": CeleryErrorCategory.TASK_RETRY,
    "NoResultFound": CeleryErrorCategory.NOTIFICATION_NOT_FOUND,
}

# Some errors don't have a specific exception class, but can be identified
# by substrings in their message.
_MESSAGE_SUBSTRING_MAP: dict[str, CeleryErrorCategory] = {
    "duplicate key value violates unique constraint": CeleryErrorCategory.DUPLICATE_RECORD,
    "notifications not found for SES references": CeleryErrorCategory.NOTIFICATION_NOT_FOUND,
    "SIGKILL": CeleryErrorCategory.SHUTDOWN,
    "Rate Exceeded": CeleryErrorCategory.THROTTLING,
    "rate exceeded": CeleryErrorCategory.THROTTLING,
    "Retry in ": CeleryErrorCategory.TASK_RETRY,
    "Throttling": CeleryErrorCategory.THROTTLING,
    "Too Many Requests": CeleryErrorCategory.THROTTLING,
    "timeout-sending-notifications": CeleryErrorCategory.TIMEOUT,
    "xray-celery": CeleryErrorCategory.XRAY,
}


def classify_error(exception: Optional[BaseException] = None) -> Tuple[CeleryErrorCategory, Optional[BaseException]]:
    """
    Walk the exception chain and classify the root cause.

    Traverses the full exception chain (following __cause__ and __context__)
    to find the deepest/root exception, then classifies it by checking:
    1. Exception class name against `_EXCEPTION_CLASS_MAP`
    2. Exception message against `_MESSAGE_SUBSTRING_MAP`

    Returns a tuple of (category, root_exception) where root_exception is the
    deepest exception in the chain, or None if the input exception is None.
    """
    if exception is None:
        return (CeleryErrorCategory.UNKNOWN, None)

    # Build the full exception chain from outer to root, detecting cycles
    exception_chain: list[BaseException] = []
    seen_exception_ids: set[int] = set()
    exc: Optional[BaseException] = exception

    while exc is not None:
        exc_id = id(exc)
        if exc_id in seen_exception_ids:
            # Break if we detect a cycle (prevents infinite loops)
            break
        seen_exception_ids.add(exc_id)
        exception_chain.append(exc)
        exc = exc.__cause__ or exc.__context__

    # The last element is the deepest/root exception
    root_exception = exception_chain[-1] if exception_chain else exception

    # Reverse to start from the deepest/root exception
    exception_chain.reverse()

    # Check each exception in the chain, starting from the root
    for exc in exception_chain:
        exc_class_name = type(exc).__name__
        exc_message = str(exc)

        # Check class name
        for pattern, category in _EXCEPTION_CLASS_MAP.items():
            if pattern in exc_class_name:
                return (category, root_exception)

        # Check message substrings
        for pattern, category in _MESSAGE_SUBSTRING_MAP.items():
            if pattern in exc_message:
                return (category, root_exception)

    return (CeleryErrorCategory.UNKNOWN, root_exception)
