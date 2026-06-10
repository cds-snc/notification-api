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

    def __init__(self, cap_per_minute: int) -> None:
        self.cap_per_minute = cap_per_minute

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
# Module-level rate limiter instance
# ============================================================================
# For the in-memory backend, this instance is process-local: it is shared only
# within the current Python process (for example, one Flask/Celery worker
# process) and is not coordinated across multiple Celery worker processes,
# pods, or hosts.
#
# As a result, the in-memory backend does not provide a true global cap unless
# deployment is constrained so that only a single worker process/pod consumes
# the relevant queue. Phase 2 should use a Redis-backed implementation to
# enforce a global cross-process rate limit without changing task code.
# ============================================================================

_rate_limiter_instance: RateLimiter | None = None


def _build_limiter_registry() -> dict[str, type[RateLimiter]]:
    """Lazily populate the registry after all classes are defined."""
    return {
        "InMemoryRateLimiter": InMemoryRateLimiter,
        "RedisSlidingWindowLogRateLimiter": RedisSlidingWindowLogRateLimiter,
        "RedisTokenBucketRateLimiter": RedisTokenBucketRateLimiter,
    }


def initialize_rate_limiter(cap_per_minute: int, limiter_class: type[RateLimiter] | None = None) -> RateLimiter:
    """
    Initialize the global rate limiter instance.

    Called during app initialization (see app/__init__.py).

    The backend is chosen in this order:
    1. limiter_class argument — if provided, instantiated directly.
    2. SMS_RATE_LIMITER_BACKEND config value — must be the exact class name
       (e.g. "RedisTokenBucketRateLimiter"). Unknown names fall back to
       InMemoryRateLimiter with a warning.
    3. Default: InMemoryRateLimiter.

    Args:
        cap_per_minute (int): Maximum SMS parts per minute.
        limiter_class (type[RateLimiter] | None): Implementation class to use.
            If None, the class is resolved from config/default.

    Returns:
        RateLimiter: The initialized rate limiter instance.
    """
    import logging

    global _rate_limiter_instance

    logger = logging.getLogger(__name__)

    if limiter_class is not None:
        resolved_class = limiter_class
    else:
        registry = _build_limiter_registry()
        class_name = "InMemoryRateLimiter"  # default
        try:
            from app.config import Config

            class_name = getattr(Config, "SMS_RATE_LIMITER_BACKEND", "InMemoryRateLimiter")
        except (ImportError, AttributeError) as exc:
            logger.warning(
                "SMS rate limiter: failed to read SMS_RATE_LIMITER_BACKEND from config; "
                "falling back to InMemoryRateLimiter. Error: %s",
                exc,
            )

        if class_name not in registry:
            logger.warning(
                "SMS rate limiter: unknown class name %r in SMS_RATE_LIMITER_BACKEND; " "falling back to InMemoryRateLimiter.",
                class_name,
            )
            resolved_class = InMemoryRateLimiter
        else:
            resolved_class = registry[class_name]

    logger.info("SMS rate limiter: initializing with %s", resolved_class.__name__)
    _rate_limiter_instance = resolved_class(cap_per_minute)

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


class RedisSlidingWindowLogRateLimiter(RateLimiter):
    """
    Redis-backed SMS parts rate limiter using a 60-second sliding window.

    Key structure:
    - `sms:rate_limit:entries` (sorted set)
      - Score: timestamp of when entry was added
      - Member: "entry_id:parts_count" (parts count is encoded in the member)

    This approach avoids separate key tracking and usage cache inconsistency.
    Parts counts are extracted via regex when needed.
    """

    WINDOW_SIZE_SECONDS = 60
    REDIS_KEY_ENTRIES = "sms:rate_limit:entries"

    def __init__(self, cap_per_minute: int, redis_client=None):
        """
        Initialize the Redis-backed rate limiter.

        Args:
            cap_per_minute (int): Maximum SMS parts allowed per minute.
            redis_client: Redis client instance. If None, uses app's redis_store.
        """
        self.cap_per_minute = cap_per_minute
        self.redis_client = redis_client
        self._lua_scripts: dict[str, object] = {}

    @property
    def redis(self):
        # Lazy-load Redis client to avoid circular imports at init time.
        if self.redis_client is not None:
            return self.redis_client
        from app import redis_store

        return redis_store

    def _get_acquire_lua_script(self):
        if "acquire" not in self._lua_scripts:
            lua_code = """
            local entries_key = KEYS[1]

            local cap_per_minute = tonumber(ARGV[1])
            local parts_count = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            local entry_id = ARGV[4]
            local window_size = tonumber(ARGV[5])

            local window_start = now - window_size

            -- 1. Remove expired entries
            redis.call('ZREMRANGEBYSCORE', entries_key, '-inf', '(' .. window_start)

            -- 2. Compute current usage by summing parts from members
            local current_usage = 0
            local entries = redis.call('ZRANGE', entries_key, 0, -1)

            for i = 1, #entries do
                local member = entries[i]
                local sep = string.find(member, ":")
                local parts = tonumber(string.sub(member, sep + 1)) or 0
                current_usage = current_usage + parts
            end

            -- 3. Check capacity
            if current_usage + parts_count <= cap_per_minute then
                local member = entry_id .. ":" .. parts_count

                redis.call('ZADD', entries_key, now, member)
                redis.call('EXPIRE', entries_key, window_size + 10)

                return {1, 0}
            else
                -- 4. Calculate wait time
                local remaining_needed = current_usage + parts_count - cap_per_minute
                local parts_freed = 0
                local last_timestamp_to_wait = nil

                local entries_with_scores = redis.call('ZRANGE', entries_key, 0, -1, 'WITHSCORES')

                for i = 1, #entries_with_scores, 2 do
                    local member = entries_with_scores[i]
                    local timestamp = tonumber(entries_with_scores[i + 1])

                    local sep = string.find(member, ":")
                    local parts = tonumber(string.sub(member, sep + 1)) or 0
                    parts_freed = parts_freed + parts
                    last_timestamp_to_wait = timestamp

                    if parts_freed >= remaining_needed then
                        break
                    end
                end

                local seconds_to_wait = 1
                if last_timestamp_to_wait ~= nil then
                    local seconds_until_expires = window_size - (now - last_timestamp_to_wait)
                    seconds_to_wait = math.max(1, math.ceil(seconds_until_expires))
                end

                return {0, seconds_to_wait}
            end
            """
            self._lua_scripts["acquire"] = self.redis.register_script(lua_code)

        return self._lua_scripts["acquire"]

    def acquire_lease(self, parts_count: int) -> Tuple[bool, int]:
        """
        Attempt to acquire capacity for SMS parts.

        Args:
            parts_count (int): Number of parts (fragments) to send.

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

        import uuid

        now = time()
        entry_id = str(uuid.uuid4())

        script = self._get_acquire_lua_script()
        result = script(
            keys=[self.REDIS_KEY_ENTRIES],
            args=[
                self.cap_per_minute,
                parts_count,
                now,
                entry_id,
                self.WINDOW_SIZE_SECONDS,
            ],
        )

        success, wait_seconds = result[0], result[1]

        if success:
            current_app.logger.info(f"SMS rate limiter (Redis): acquired {parts_count} parts. " f"Entry ID: {entry_id}")
        else:
            current_app.logger.warning(
                f"SMS rate limiter (Redis): capacity exhausted. Requested {parts_count} parts. "
                f"Will retry in {wait_seconds} seconds."
            )

        return bool(success), wait_seconds

    def get_current_usage(self) -> int:
        """Get the current parts count in the active 60-second window from Redis."""
        now = time()
        window_start = now - self.WINDOW_SIZE_SECONDS

        # Remove expired entries
        self.redis.zremrangebyscore(self.REDIS_KEY_ENTRIES, "-inf", f"({window_start}")

        # Recalculate usage by summing parts from members (encoded as "entry_id:parts")
        current_usage = 0
        entries = self.redis.zrange(self.REDIS_KEY_ENTRIES, 0, -1)
        for member in entries:
            # Extract parts count from member string format "entry_id:parts_count"
            if isinstance(member, bytes):
                member = member.decode("utf-8")
            parts_str = member.split(":")[-1] if ":" in member else "0"
            try:
                current_usage += int(parts_str)
            except ValueError:
                current_app.logger.warning(
                    f"SMS rate limiter (Redis): skipping malformed usage entry member={member!r}, parts={parts_str!r}"
                )

        return current_usage

    def reset_limiter(self):
        self.redis.delete(self.REDIS_KEY_ENTRIES)

        current_app.logger.info("SMS rate limiter entries cleared")


class RedisTokenBucketRateLimiter(RateLimiter):
    """
    Redis-backed SMS parts rate limiter using a token bucket algorithm.

    Key structure:
    - `sms:rate_limit:token_bucket` (hash)
      - Field `tokens`: current available capacity (float, stored as string)
      - Field `last_refill`: timestamp of last refill (float, stored as string)

    Algorithm:
    - Tokens refill continuously at rate cap_per_minute / 60 per second.
    - On each request, elapsed time since last refill is computed, tokens are
      topped up (capped at cap_per_minute), and the requested parts are
      subtracted atomically in Lua.
    - If tokens are insufficient, the exact wait time is returned:
      deficit / (cap_per_minute / 60) seconds.
    - Burst after idle: if the system is idle, the bucket refills to cap,
      allowing a full cap's worth of parts to be sent immediately.

    Complexity: O(1) for all operations.
    """

    REDIS_KEY = "sms:rate_limit:token_bucket"

    def __init__(self, cap_per_minute: int, redis_client=None):
        """
        Initialize the Redis token bucket rate limiter.

        Args:
            cap_per_minute (int): Maximum SMS parts allowed per minute.
            redis_client: Redis client instance. If None, uses app's redis_store.
        """
        self.cap_per_minute = cap_per_minute
        self.redis_client = redis_client
        self._lua_scripts: dict[str, object] = {}

    @property
    def redis(self):
        # Lazy-load Redis client to avoid circular imports at init time.
        if self.redis_client is not None:
            return self.redis_client
        from app import redis_store

        return redis_store

    def _get_acquire_lua_script(self):
        if "acquire" not in self._lua_scripts:
            lua_code = """
            local key = KEYS[1]
            local cap = tonumber(ARGV[1])
            local parts_count = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            local refill_rate = cap / 60.0

            -- Read current state; default to full bucket on first call
            local tokens_str = redis.call('HGET', key, 'tokens')
            local last_refill_str = redis.call('HGET', key, 'last_refill')

            local tokens
            local last_refill
            if tokens_str == false then
                tokens = cap
                last_refill = now
            else
                tokens = tonumber(tokens_str)
                last_refill = tonumber(last_refill_str)
            end

            -- Refill tokens based on elapsed time
            local elapsed = now - last_refill
            tokens = math.min(cap, tokens + elapsed * refill_rate)

            if tokens >= parts_count then
                -- Admit: subtract parts and persist new state
                tokens = tokens - parts_count
                redis.call('HSET', key, 'tokens', tostring(tokens), 'last_refill', tostring(now))
                return {1, 0}
            else
                -- Reject: compute exact wait time
                local deficit = parts_count - tokens
                local seconds_to_wait = math.ceil(deficit / refill_rate)
                seconds_to_wait = math.max(1, seconds_to_wait)
                -- Persist refreshed token count and timestamp even on reject
                redis.call('HSET', key, 'tokens', tostring(tokens), 'last_refill', tostring(now))
                return {0, seconds_to_wait}
            end
            """
            self._lua_scripts["acquire"] = self.redis.register_script(lua_code)

        return self._lua_scripts["acquire"]

    def acquire_lease(self, parts_count: int) -> Tuple[bool, int]:
        """
        Attempt to acquire capacity for SMS parts.

        Args:
            parts_count (int): Number of parts (fragments) to send.

        Returns:
            Tuple[bool, int]:
                - (True, 0) if parts can be sent immediately.
                - (False, seconds_remaining) if rate limit exhausted;
                  seconds_remaining is the exact time until enough tokens refill.
        """
        if parts_count <= 0:
            raise ValueError("parts_count must be positive")

        if parts_count > self.cap_per_minute:
            raise ValueError("parts_count must be smaller than or equal to the cap_per_minute")

        now = time()
        script = self._get_acquire_lua_script()
        result = script(
            keys=[self.REDIS_KEY],
            args=[self.cap_per_minute, parts_count, now],
        )

        success, wait_seconds = result[0], result[1]

        if success:
            current_app.logger.info(f"SMS rate limiter (token bucket): acquired {parts_count} parts.")
        else:
            current_app.logger.warning(
                f"SMS rate limiter (token bucket): capacity exhausted. Requested {parts_count} parts. "
                f"Will retry in {wait_seconds} seconds."
            )

        return bool(success), int(wait_seconds)

    def get_current_usage(self) -> int:
        """
        Get current consumed capacity equivalent.

        Returns cap minus available tokens after applying any pending refill.
        This is a non-atomic read — do not rely on it for admission decisions.
        """
        now = time()
        tokens_str = self.redis.hget(self.REDIS_KEY, "tokens")
        last_refill_str = self.redis.hget(self.REDIS_KEY, "last_refill")

        if tokens_str is None:
            return 0

        tokens = float(tokens_str if isinstance(tokens_str, str) else tokens_str.decode("utf-8"))
        last_refill = float(last_refill_str if isinstance(last_refill_str, str) else last_refill_str.decode("utf-8"))

        elapsed = now - last_refill
        refill_rate = self.cap_per_minute / 60.0
        tokens = min(self.cap_per_minute, tokens + elapsed * refill_rate)

        return max(0, int(self.cap_per_minute - tokens))

    def reset_limiter(self):
        self.redis.delete(self.REDIS_KEY)
        current_app.logger.info("SMS rate limiter (token bucket): reset")
