from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import current_app

from app import redis_store
from app.models import DELIVERY_STATUS_CALLBACK_TYPE


def _is_callback_auto_suspend_enabled() -> bool:
    return bool(current_app.config.get("FF_CALLBACK_AUTO_SUSPEND", True))


def _normalize_callback_type(callback_type: str | None) -> str:
    return callback_type or DELIVERY_STATUS_CALLBACK_TYPE


def _base_key(service_id: str, callback_type: str | None) -> str:
    normalized_type = _normalize_callback_type(callback_type)
    return f"service-callback-backoff:{service_id}:{normalized_type}"


def _failure_count_key(service_id: str, callback_type: str | None) -> str:
    return f"{_base_key(service_id, callback_type)}:failures"


def _suspended_until_key(service_id: str, callback_type: str | None) -> str:
    return f"{_base_key(service_id, callback_type)}:suspended-until"


def _warning_email_key(service_id: str, callback_type: str | None) -> str:
    return f"{_base_key(service_id, callback_type)}:warning-email"


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _get_int_config(config_name: str, default: int) -> int:
    value = current_app.config.get(config_name, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _get_float_config(config_name: str, default: float) -> float:
    value = current_app.config.get(config_name, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    # Keep jitter bounded to avoid zero/negative delays.
    return min(max(parsed, 0.0), 0.95)


def _get_failure_count(service_id: str, callback_type: str | None) -> int:
    count = _to_text(redis_store.get(_failure_count_key(service_id, callback_type)))
    if count is None:
        return 0
    try:
        return max(0, int(count))
    except (TypeError, ValueError):
        return 0


def _calculate_backoff_seconds(failure_count: int) -> int:
    base_delay_seconds = _get_int_config("CALLBACK_AUTO_SUSPEND_BASE_DELAY_SECONDS", 60)
    max_delay_seconds = _get_int_config("CALLBACK_AUTO_SUSPEND_MAX_DELAY_SECONDS", 3600)
    jitter_factor = _get_float_config("CALLBACK_AUTO_SUSPEND_JITTER_FACTOR", 0.2)

    exponential_delay = base_delay_seconds * (2 ** max(0, failure_count - 1))
    capped_delay = min(exponential_delay, max_delay_seconds)
    jitter_multiplier = random.uniform(1 - jitter_factor, 1 + jitter_factor)
    jittered_delay = int(round(capped_delay * jitter_multiplier))
    return max(1, min(jittered_delay, max_delay_seconds))


def is_callback_auto_suspended(service_id: str, callback_type: str | None) -> bool:
    if not _is_callback_auto_suspend_enabled():
        return False
    return bool(redis_store.get(_suspended_until_key(service_id, callback_type)))


def get_callback_auto_suspended_until(service_id: str, callback_type: str | None) -> str | None:
    if not _is_callback_auto_suspend_enabled():
        return None
    return _to_text(redis_store.get(_suspended_until_key(service_id, callback_type)))


def get_callback_runtime_state(service_id: str, callback_type: str | None) -> dict[str, str | bool | None]:
    auto_suspended_until = get_callback_auto_suspended_until(service_id, callback_type)
    return {
        "is_auto_suspended": auto_suspended_until is not None,
        "auto_suspended_until": auto_suspended_until,
    }


def register_callback_failure(service_id: str, callback_type: str | None) -> dict[str, Any]:
    if not _is_callback_auto_suspend_enabled():
        return {
            "failure_count": 0,
            "retry_delay_seconds": None,
            "suspended_until": None,
            "entered_auto_suspension": False,
        }

    was_auto_suspended = is_callback_auto_suspended(service_id, callback_type)
    failure_count = _get_failure_count(service_id, callback_type) + 1
    retry_delay_seconds = _calculate_backoff_seconds(failure_count)
    max_delay_seconds = _get_int_config("CALLBACK_AUTO_SUSPEND_MAX_DELAY_SECONDS", 3600)
    # Keep failure count long enough for consecutive failures to continue backing off.
    failure_count_ttl_seconds = max(max_delay_seconds * 2, retry_delay_seconds)
    suspended_until = datetime.now(timezone.utc) + timedelta(seconds=retry_delay_seconds)

    redis_store.set(_failure_count_key(service_id, callback_type), failure_count, ex=failure_count_ttl_seconds)
    redis_store.set(
        _suspended_until_key(service_id, callback_type),
        suspended_until.isoformat(),
        ex=retry_delay_seconds,
    )

    return {
        "failure_count": failure_count,
        "retry_delay_seconds": retry_delay_seconds,
        "suspended_until": suspended_until,
        "entered_auto_suspension": not was_auto_suspended,
    }


def clear_callback_backoff_state(service_id: str, callback_type: str | None):
    if not _is_callback_auto_suspend_enabled():
        return

    redis_store.delete(_failure_count_key(service_id, callback_type))
    redis_store.delete(_suspended_until_key(service_id, callback_type))


def should_send_callback_warning_email(service_id: str, callback_type: str | None) -> bool:
    if not _is_callback_auto_suspend_enabled():
        return False

    warning_frequency_seconds = _get_int_config("CALLBACK_AUTO_SUSPEND_WARNING_FREQUENCY_SECONDS", 86400)
    warning_key = _warning_email_key(service_id, callback_type)

    if redis_store.get(warning_key):
        return False

    redis_store.set(warning_key, "1", ex=warning_frequency_seconds)
    return True
