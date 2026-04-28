# app/rate_limiter.py
"""
Rate Limiting Module

This module provides rate limiting for SMS parts delivery. It enforces a cap
on the number of SMS parts (fragments) that can be sent per minute.
"""

import math
from abc import ABC, abstractmethod
from collections import deque
from time import time
from typing import Tuple

from flask import current_app


class RateLimiter(ABC):
    """
    Abstract base class defining the rate limiter interface.

    Implementations should track parts capacity over time and enforce limits.
    Phase 2 will provide a Redis-backed implementation.
    """

    @abstractmethod
    def acquire_lease(self, parts_count: int) -> Tuple[bool, int]:
        """
        Attempt to acquire a lease for the given number of SMS parts.

        Args:
            parts_count (int): Number of SMS parts (fragments) to send.

        Returns:
            Tuple[bool, int]:
                - bool: True if parts can be sent now, False if rate limit hit.
                - int: If True, returns 0. If False, returns seconds to wait before retry.
        """
        pass

    @abstractmethod
    def get_current_usage(self) -> int:
        """
        Get the current parts count in the active window.

        Returns:
            int: Number of parts used in the current window.
        """
        pass


class InMemoryRateLimiter(RateLimiter):
    """
    In-memory SMS parts rate limiter using a 60-second sliding window.

    This implementation tracks parts sent in the current minute and enforces
    the configured parts cap.

    Algorithm:
    - Maintains a deque of (timestamp, parts_count) tuples.
    - Keeps a running total (current_usage) updated on append/popleft.
    - On each acquire_lease(), removes entries older than 60 seconds.
    - Checks if current_usage + new_parts exceeds the cap.
    - If capacity available, records the entry and updates running total.
    - If capacity exhausted, calculates when enough entries will have expired
      to accommodate the new request.
    """

    WINDOW_SIZE_SECONDS = 60

    def __init__(self, cap_per_minute: int):
        """
        Initialize the in-memory rate limiter.

        Args:
            cap_per_minute (int): Maximum SMS parts allowed per minute.
                                  E.g., 1000 parts/minute.
        """
        self.cap_per_minute = cap_per_minute
        self.window: deque = deque()  # Stores (timestamp, parts_count) tuples
        self.current_usage: int = 0  # Running total of parts in the current window

    def acquire_lease(self, parts_count: int) -> Tuple[bool, int]:
        """
        Attempt to acquire capacity for SMS parts.

        Args:
            parts_count (int): Number of parts to send.

        Returns:
            Tuple[bool, int]:
                - (True, 0) if parts can be sent immediately.
                - (False, seconds_remaining) if rate limit exhausted;
                  seconds_remaining is the time until enough entries expire to
                  accommodate the requested parts.
        """
        if parts_count <= 0:
            raise ValueError("parts_count must be positive")

        if parts_count > self.cap_per_minute:
            raise ValueError("parts_count must be smaller than or equal to the cap_per_minute")

        now = time()
        window_start = now - self.WINDOW_SIZE_SECONDS

        # Remove entries older than the 60-second window and update running total
        while self.window and self.window[0][0] < window_start:
            _, old_parts = self.window.popleft()
            self.current_usage -= old_parts

        # Check if adding new parts exceeds the cap
        if self.current_usage + parts_count <= self.cap_per_minute:
            # Enough parts available: record the entry and update running total
            self.window.append((now, parts_count))
            self.current_usage += parts_count
            current_app.logger.info(
                f"SMS rate limiter: acquired {parts_count} parts. " f"Window usage: {self.current_usage}/{self.cap_per_minute}"
            )
            return True, 0

        # Not enough capacity: calculate when enough parts will be available for the new request
        remaining_parts_needed = self.current_usage + parts_count - self.cap_per_minute
        parts_freed = 0
        last_timestamp_to_wait_for = None

        # Iterate through window entries (oldest first) to find when we'll have enough space
        for timestamp, parts in self.window:
            parts_freed += parts
            last_timestamp_to_wait_for = timestamp
            if parts_freed >= remaining_parts_needed:
                # This entry needs to expire to free enough space
                break

        # Calculate seconds to wait for the last entry to expire
        if last_timestamp_to_wait_for is not None:
            seconds_until_expires = self.WINDOW_SIZE_SECONDS - (now - last_timestamp_to_wait_for)
            seconds_to_wait = max(1, math.ceil(seconds_until_expires))
        else:
            # Fallback (shouldn't reach here)
            seconds_to_wait = 1

        current_app.logger.warning(
            f"SMS rate limiter: capacity exhausted. Requested {parts_count} parts "
            f"but only {self.cap_per_minute - self.current_usage} available in current window. "
            f"Will retry in {seconds_to_wait} seconds."
        )
        return False, seconds_to_wait

    def reset_limiter(self):
        """Reset the rate limiter (clears all entries and running total)."""
        self.window.clear()
        self.current_usage = 0
        current_app.logger.info("SMS rate limiter: reset (window cleared)")

    def get_current_usage(self) -> int:
        """Get the current parts count in the active 60-second window."""
        now = time()
        window_start = now - self.WINDOW_SIZE_SECONDS

        # Remove expired entries and update running total
        while self.window and self.window[0][0] < window_start:
            _, old_parts = self.window.popleft()
            self.current_usage -= old_parts

        return self.current_usage


# ============================================================================
# Module-level instance: Global rate limiter for the entire application
# ============================================================================
# This instance is created once per Flask app and shared across all Celery tasks.
# It tracks parts sent across all services globally (not per-service).
#
# In Phase 2, this will be replaced with a Redis-backed instance via feature flag
# or environment configuration, without changing any task code.
# ============================================================================

_rate_limiter_instance: RateLimiter | None = None


def initialize_rate_limiter(cap_per_minute: int) -> RateLimiter:
    """
    Initialize the global rate limiter instance.

    Called during app initialization (see app/__init__.py).

    Args:
        cap_per_minute (int): Maximum SMS parts per minute.

    Returns:
        RateLimiter: The initialized rate limiter instance.
    """
    global _rate_limiter_instance
    _rate_limiter_instance = InMemoryRateLimiter(cap_per_minute)
    return _rate_limiter_instance


def get_rate_limiter() -> RateLimiter:
    """
    Get the global rate limiter instance.

    Call this from tasks to access the rate limiter.
    Raises RuntimeError if initialize_rate_limiter() hasn't been called.

    Returns:
        RateLimiter: The global rate limiter instance.

    Raises:
        RuntimeError: If the rate limiter hasn't been initialized.
    """
    if _rate_limiter_instance is None:
        raise RuntimeError(
            "SMS rate limiter not initialized. " "Call initialize_rate_limiter() during app startup (app/__init__.py)."
        )
    return _rate_limiter_instance
