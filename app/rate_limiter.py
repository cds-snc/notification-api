# app/rate_limiter.py
"""
Rate Limiting Module

This module provides rate limiting for SMS parts delivery. It enforces a cap
on the number of SMS parts (fragments) that can be sent per minute.
"""

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
        Attempt to acquire capacity for the given number of SMS parts.

        Args:
            parts_count (int): Number of SMS parts (fragments) to send.

        Returns:
            Tuple[bool, int]:
                - bool: True if parts can be sent now, False if rate limit hit.
                - int: If True, returns 0. If False, returns seconds to wait before retry.
        """
        pass

    @abstractmethod
    def reset_limiter(self):
        """
        Reset the rate limiter state.
        """
        pass

    @abstractmethod
    def get_current_usage(self) -> int:
        """
        Get the current parts count in the active window.

        Returns:
            int: Number of parts consumed in the current window.
        """
        pass


class InMemoryRateLimiter(RateLimiter):
    """
    In-memory SMS parts rate limiter using a 60-second sliding window.

    This implementation tracks parts sent in the current minute and enforces
    the configured parts cap.

    Algorithm:
    - Maintains a deque of (timestamp, parts_count) tuples.
    - On each acquire_lease(), removes entries older than 60 seconds.
    - Sums remaining parts and checks if adding new parts exceeds the cap.
    - If capacity available, records the entry and returns (True, 0).
    - If capacity exhausted, calculates seconds until oldest entry expires.
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

    def acquire_lease(self, parts_count: int) -> Tuple[bool, int]:
        """
        Attempt to acquire capacity for SMS parts.

        Args:
            parts_count (int): Number of parts to send.

        Returns:
            Tuple[bool, int]:
                - (True, 0) if parts can be sent immediately.
                - (False, seconds_remaining) if rate limit exhausted;
                  seconds_remaining is the time until the oldest window entry expires.
        """
        if parts_count <= 0:
            raise ValueError("parts_count must be positive")

        now = time()
        cutoff_time = now - self.WINDOW_SIZE_SECONDS

        # Remove entries older than the 60-second window
        while self.window and self.window[0][0] < cutoff_time:
            self.window.popleft()

        # Sum parts in the current window
        current_usage = sum(parts for _, parts in self.window)

        # Check if adding new parts exceeds the cap
        if current_usage + parts_count <= self.cap_per_minute:
            # Capacity available: record the entry
            self.window.append((now, parts_count))
            current_app.logger.info(
                f"SMS rate limiter: acquired {parts_count} parts. "
                f"Window usage: {current_usage + parts_count}/{self.cap_per_minute}"
            )
            return True, 0

        # Capacity exhausted: calculate retry delay
        if self.window:
            oldest_timestamp = self.window[0][0]
            seconds_until_oldest_expires = self.WINDOW_SIZE_SECONDS - (now - oldest_timestamp)
            # Ensure at least 1 second to avoid busy-loop retries
            seconds_to_wait = max(1, int(seconds_until_oldest_expires) + 1)
        else:
            # Edge case: window is empty but cap is exceeded (shouldn't happen)
            seconds_to_wait = 1

        current_app.logger.warning(
            f"SMS rate limiter: capacity exhausted. Requested {parts_count} parts "
            f"but only {self.cap_per_minute - current_usage} available in current window. "
            f"Will retry in {seconds_to_wait} seconds."
        )
        return False, seconds_to_wait

    def reset_limiter(self):
        """Reset the rate limiter (clears all entries)."""
        self.window.clear()
        current_app.logger.info("SMS rate limiter: reset (window cleared)")

    def get_current_usage(self) -> int:
        """Get the current parts count in the active 60-second window."""
        now = time()
        cutoff_time = now - self.WINDOW_SIZE_SECONDS

        # Remove stale entries first
        while self.window and self.window[0][0] < cutoff_time:
            self.window.popleft()

        return sum(parts for _, parts in self.window)


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
