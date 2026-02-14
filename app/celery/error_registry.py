"""
Celery error classification for CloudWatch alarm differentiation.

Known/expected errors are tagged with a category marker in the logs so that
the log filters can distinguish them from truly unexpected errors.
"""

from enum import Enum
from typing import Optional


# The categories themselves are defined here, along with the logic to classify
# exceptions into categories. The actual logging of these classifications is
# performed by NotifyTask.on_failure in app/celery/celery.py to avoid coupling the
# error classification logic with the Celery app setup.
class CeleryErrorCategory(str, Enum):
    """Categories of Celery errors for log metric differentiation."""

    # Transient AWS errors — expected under load, retry will handle them
    THROTTLING = "CELERY_KNOWN_ERROR::THROTTLING"

    # Duplicate DB records in an idempotent system — safe to ignore
    DUPLICATE_RECORD = "CELERY_KNOWN_ERROR::DUPLICATE_RECORD"

    # Unknown / unclassified — these should trigger sensitive alarms
    UNKNOWN = "CELERY_UNKNOWN_ERROR"


# Map exception class names (or substrings in the message) to categories.
# Order matters: first match wins.
_EXCEPTION_CLASS_MAP: dict[str, CeleryErrorCategory] = {
    "ThrottlingException": CeleryErrorCategory.THROTTLING,
    "TooManyRequestsException": CeleryErrorCategory.THROTTLING,
    "RequestLimitExceeded": CeleryErrorCategory.THROTTLING,
    "IntegrityError": CeleryErrorCategory.DUPLICATE_RECORD,
}

# Some errors don't have a specific exception class, but can be identified
# by substrings in their message.
_MESSAGE_SUBSTRING_MAP: dict[str, CeleryErrorCategory] = {
    "Rate Exceeded": CeleryErrorCategory.THROTTLING,
    "rate exceeded": CeleryErrorCategory.THROTTLING,
    "Throttling": CeleryErrorCategory.THROTTLING,
    "Too Many Requests": CeleryErrorCategory.THROTTLING,
    "duplicate key value": CeleryErrorCategory.DUPLICATE_RECORD,
    "already exists": CeleryErrorCategory.DUPLICATE_RECORD,
}


def classify_error(exception: Optional[BaseException] = None) -> CeleryErrorCategory:
    """
    Walk the exception chain and classify the root cause.

    The matching CeleryErrorCategory is determined by checking if the
    exception class name contains any key from `_EXCEPTION_CLASS_MAP`,
    or if the exception message contains any key from `_MESSAGE_SUBSTRING_MAP`.

    Returns the first matching CeleryErrorCategory found, or UNKNOWN.
    """
    if exception is None:
        return CeleryErrorCategory.UNKNOWN

    # Walk the full chain: exception -> __cause__ -> __context__
    exc: Optional[BaseException] = exception
    while exc is not None:
        exc_class_name = type(exc).__name__
        exc_message = str(exc)

        # Check class name
        for pattern, category in _EXCEPTION_CLASS_MAP.items():
            if pattern in exc_class_name:
                return category

        # Check message substrings
        for pattern, category in _MESSAGE_SUBSTRING_MAP.items():
            if pattern in exc_message:
                return category

        # Traverse the chain
        exc = exc.__cause__ or exc.__context__

    return CeleryErrorCategory.UNKNOWN
