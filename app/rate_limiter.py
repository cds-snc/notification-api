# app/rate_limiter.py
from __future__ import annotations

"""
Rate Limiting Module

This module provides a generic rate limiter that enforces a cap on the number
of units that can be acquired per minute.
"""

import logging
import math
import threading
import uuid
from abc import ABC, abstractmethod
from collections import deque
from time import time
from typing import Tuple

from flask import current_app

_logger = logging.getLogger(__name__)

# Sentinel scope used when a caller does not partition by `for_scope`.
_DEFAULT_SCOPE = "default"


class RateLimiter(ABC):
    """
    Abstract base class defining the rate limiter interface.

    Implementations should track unit capacity over time and enforce limits.
    Backends may partition their state by an optional `scope` string; see
    :meth:`for_scope` and the ``_*_scoped`` hooks.
    """

    def __init__(self, cap_per_minute: int, namespace: str) -> None:
        self.cap_per_minute = cap_per_minute
        self.namespace = namespace

    @abstractmethod
    def acquire_lease(self, units: int = 1) -> Tuple[bool, int]:
        """
        Attempt to acquire a lease for the given number of units.

        Args:
            units (int): Number of units to acquire. Defaults to 1.

        Returns:
            Tuple[bool, int]:
                - bool: True if units can be acquired now, False if rate limit hit.
                - int: If True, returns 0. If False, returns seconds to wait before retry.
        """
        pass

    @abstractmethod
    def get_current_usage(self) -> int:
        """
        Get the current unit count in the active window.

        Returns:
            int: Number of units used in the current window.
        """
        pass

    @property
    def max_units_per_acquire(self) -> int:
        """
        Maximum units that can be requested in a single acquire_lease() call.

        Defaults to cap_per_minute. Implementations with a tighter per-call
        ceiling (e.g. RedisTokenBucketRateLimiter) should override this.
        """
        return self.cap_per_minute

    def _max_units_for_cap(self, cap_override: int | None) -> int:
        """Effective per-call ceiling for a given cap override.

        Overridden by backends whose ceiling is not the cap itself (e.g. the
        token-bucket ceiling is ``max(1, cap // 60)``).
        """
        return cap_override if cap_override is not None else self.cap_per_minute

    def _acquire_lease_scoped(self, units: int, *, scope: str, cap_override: int | None) -> Tuple[bool, int]:
        """Scoped variant of :meth:`acquire_lease`. Concrete backends override."""
        raise NotImplementedError(f"{type(self).__name__} does not support scoped rate limiting")

    def _get_current_usage_scoped(self, *, scope: str) -> int:
        """Scoped variant of :meth:`get_current_usage`. Concrete backends override."""
        raise NotImplementedError(f"{type(self).__name__} does not support scoped rate limiting")

    def _reset_scoped(self, *, scope: str) -> None:
        """Reset state for a single scope. Concrete backends override."""
        raise NotImplementedError(f"{type(self).__name__} does not support scoped rate limiting")

    def buffered(self, size: int) -> BufferedRateLimiter:
        """
        Wrap this rate limiter in a BufferedRateLimiter and register it under
        the same namespace, replacing the current entry in the registry.

        Args:
            size (int): Number of tokens to pre-fetch from the underlying
                limiter per Redis call.

        Returns:
            BufferedRateLimiter: The new buffered wrapper.

        Raises:
            TypeError: If called on an already-buffered or scoped instance.
        """
        if isinstance(self, BufferedRateLimiter):
            raise TypeError(
                f"Rate limiter [{self.namespace}] is already a BufferedRateLimiter. " "Double-wrapping is not allowed."
            )
        if isinstance(self, ScopedRateLimiter):
            raise TypeError(
                f"Rate limiter [{self.namespace}] is a ScopedRateLimiter; buffered() is not supported on scoped views."
            )
        buffered_limiter = BufferedRateLimiter(self, size)
        _rate_limiter_instances[self.namespace] = buffered_limiter
        return buffered_limiter

    def for_scope(self, scope: str, cap: int | None = None) -> ScopedRateLimiter:
        """Return a lightweight scoped view of this limiter.

        The returned :class:`ScopedRateLimiter` delegates every call to this
        instance, narrowing state access to ``scope`` and optionally overriding
        the cap. Each call returns a new view; views hold no state of their own.

        Args:
            scope: Non-empty partition key (e.g. a service id).
            cap: Optional per-scope cap override. When ``None``, the parent's
                ``cap_per_minute`` applies.

        Raises:
            TypeError: If called on a :class:`BufferedRateLimiter` or another
                :class:`ScopedRateLimiter`.
        """
        if isinstance(self, BufferedRateLimiter):
            raise TypeError(f"Rate limiter [{self.namespace}] is a BufferedRateLimiter; " "scope the underlying limiter instead.")
        if isinstance(self, ScopedRateLimiter):
            raise TypeError(
                f"Rate limiter [{self.namespace}] is already a ScopedRateLimiter; " "nested scoping is not supported."
            )
        return ScopedRateLimiter(self, scope=scope, cap_override=cap)


class InMemoryRateLimiter(RateLimiter):
    """
    In-memory rate limiter using a 60-second sliding window.

    This implementation tracks units acquired in the current minute and enforces
    the configured cap.

    Algorithm:
    - Maintains a per-scope deque of (timestamp, units) tuples.
    - Keeps a per-scope running total updated on append/popleft.
    - On each acquire_lease(), removes entries older than 60 seconds.
    - Checks if current_usage + new_units exceeds the cap.
    - If capacity available, records the entry and updates running total.
    - If capacity exhausted, calculates when enough entries will have expired
      to accommodate the new request.

    Scoping:
    State is partitioned by an internal ``scope`` string (defaulting to
    ``"default"``). Scoped views obtained via :meth:`for_scope` narrow every
    operation to their scope; unscoped calls target ``"default"``. Empty
    non-default scope entries are lazily GC'd to keep the scope dicts bounded.

    Thread safety:
    A ``threading.Lock`` serialises all compound read-modify-write operations
    so multiple threads in the same process share one consistent view of the
    sliding window.

    Deployment note:
    Suitable only for single-process deployments (e.g. one Celery worker with
    multiple threads).  State is not shared across multiple worker processes,
    pods, or hosts — use a Redis-backed implementation for multi-process setups.
    """

    WINDOW_SIZE_SECONDS = 60

    def __init__(self, cap_per_minute: int, namespace: str):
        """
        Initialize the in-memory rate limiter.

        Args:
            cap_per_minute (int): Maximum units allowed per minute.
                                  E.g., 1000 units/minute.
            namespace (str): Logical name for this limiter (used in log messages).
        """
        super().__init__(cap_per_minute, namespace)
        self._windows: dict[str, deque] = {}
        self._usage: dict[str, int] = {}
        self._lock = threading.Lock()

    # Backward-compat accessors for the default scope (used by existing tests).
    @property
    def window(self) -> deque:
        return self._windows.setdefault(_DEFAULT_SCOPE, deque())

    @property
    def current_usage(self) -> int:
        return self._usage.get(_DEFAULT_SCOPE, 0)

    def acquire_lease(self, units: int = 1) -> Tuple[bool, int]:
        """
        Attempt to acquire capacity for the given number of units on the
        default scope. See :meth:`_acquire_lease_scoped` for the scoped variant.
        """
        return self._acquire_lease_scoped(units, scope=_DEFAULT_SCOPE, cap_override=None)

    def _acquire_lease_scoped(self, units: int, *, scope: str, cap_override: int | None) -> Tuple[bool, int]:
        effective_cap = cap_override if cap_override is not None else self.cap_per_minute

        if units <= 0:
            raise ValueError("units must be positive")

        if units > effective_cap:
            raise ValueError("units must be smaller than or equal to the cap_per_minute")

        with self._lock:
            now = time()
            window_start = now - self.WINDOW_SIZE_SECONDS

            window = self._windows.setdefault(scope, deque())
            usage = self._usage.get(scope, 0)

            # Remove entries older than the window and update the running total.
            while window and window[0][0] < window_start:
                _, old_units = window.popleft()
                usage -= old_units

            if usage + units <= effective_cap:
                window.append((now, units))
                usage += units
                self._usage[scope] = usage
                current_app.logger.info(
                    f"Rate limiter [{self.namespace}:{scope}]: acquired {units} units. " f"Window usage: {usage}/{effective_cap}"
                )
                return True, 0

            # Not enough capacity: calculate when enough units will free up.
            units_needed = usage + units - effective_cap
            units_freed = 0
            last_timestamp_to_wait_for = None

            # Iterate through window entries (oldest first) to find when we'll have enough space
            for timestamp, entry_units in window:
                units_freed += entry_units
                last_timestamp_to_wait_for = timestamp
                if units_freed >= units_needed:
                    # This entry needs to expire to free enough space
                    break

            # Calculate seconds to wait for the last entry to expire
            if last_timestamp_to_wait_for is not None:
                seconds_until_expires = self.WINDOW_SIZE_SECONDS - (now - last_timestamp_to_wait_for)
                seconds_to_wait = max(1, math.ceil(seconds_until_expires))
            else:
                # Fallback (shouldn't reach here)
                seconds_to_wait = 1

            self._usage[scope] = usage
            self._maybe_gc_scope(scope, window)
            current_app.logger.warning(
                f"Rate limiter [{self.namespace}:{scope}]: capacity exhausted. Requested {units} units "
                f"but only {effective_cap - usage} available in current window. "
                f"Will retry in {seconds_to_wait} seconds."
            )
            return False, seconds_to_wait

    def _maybe_gc_scope(self, scope: str, window: deque) -> None:
        # Drop empty non-default scopes to keep the per-scope dicts bounded.
        if scope == _DEFAULT_SCOPE:
            return
        if not window and self._usage.get(scope, 0) == 0:
            self._windows.pop(scope, None)
            self._usage.pop(scope, None)

    def reset_limiter(self):
        """Reset the rate limiter — clears all scopes."""
        with self._lock:
            self._windows.clear()
            self._usage.clear()
        current_app.logger.info(f"Rate limiter [{self.namespace}]: reset (all scopes cleared)")

    def _reset_scoped(self, *, scope: str) -> None:
        with self._lock:
            self._windows.pop(scope, None)
            self._usage.pop(scope, None)
        current_app.logger.info(f"Rate limiter [{self.namespace}:{scope}]: reset")

    def get_current_usage(self) -> int:
        """Get the current unit count in the active window on the default scope."""
        return self._get_current_usage_scoped(scope=_DEFAULT_SCOPE)

    def _get_current_usage_scoped(self, *, scope: str) -> int:
        with self._lock:
            now = time()
            window_start = now - self.WINDOW_SIZE_SECONDS

            window = self._windows.get(scope)
            if window is None:
                return 0
            usage = self._usage.get(scope, 0)

            # Remove expired entries and update running total
            while window and window[0][0] < window_start:
                _, old_units = window.popleft()
                usage -= old_units

            self._usage[scope] = usage
            self._maybe_gc_scope(scope, window)
            return usage


# ============================================================================
# Module-level rate limiter registry
# ============================================================================
# Keyed by namespace (e.g. "sms"). Each entry is a RateLimiter instance
# (possibly a BufferedRateLimiter wrapping a concrete backend).
#
# For the in-memory backend, instances are process-local and not coordinated
# across multiple Celery worker processes, pods, or hosts.
# Redis-backed implementations enforce a global cross-process rate limit.
# ============================================================================

_rate_limiter_instances: dict[str, RateLimiter] = {}


def _build_limiter_registry() -> dict[str, type[RateLimiter]]:
    """Lazily populate the registry after all classes are defined."""
    return {
        "InMemoryRateLimiter": InMemoryRateLimiter,
        "RedisSlidingWindowLogRateLimiter": RedisSlidingWindowLogRateLimiter,
        "RedisTokenBucketRateLimiter": RedisTokenBucketRateLimiter,
    }


def initialize_rate_limiter(
    cap_per_minute: int, limiter_class: type[RateLimiter] | None = None, *, namespace: str
) -> RateLimiter:
    """
    Initialize a rate limiter for the given namespace and store it in the registry.

    Called during app initialization (see app/__init__.py). Returns the raw
    limiter instance; chain `.buffered(size)` to wrap it in a BufferedRateLimiter.

    The backend is chosen in this order:
    1. limiter_class argument — if provided, instantiated directly.
    2. SMS_RATE_LIMITER_BACKEND config value — must be the exact class name
       (e.g. "RedisTokenBucketRateLimiter"). Unknown names fall back to
       InMemoryRateLimiter with a warning.
    3. Default: InMemoryRateLimiter.

    Args:
        cap_per_minute (int): Maximum units per minute.
        limiter_class (type[RateLimiter] | None): Implementation class to use.
            If None, the class is resolved from config/default.
        namespace (str): Logical name for this limiter instance (e.g. "sms").
            Used in Redis key construction, log messages, and registry lookup.

    Returns:
        RateLimiter: The initialized rate limiter instance.
    """
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
                "Rate limiter: failed to read SMS_RATE_LIMITER_BACKEND from config; "
                "falling back to InMemoryRateLimiter. Error: %s",
                exc,
            )

        if class_name not in registry:
            logger.warning(
                "Rate limiter: unknown class name %r in SMS_RATE_LIMITER_BACKEND; " "falling back to InMemoryRateLimiter.",
                class_name,
            )
            resolved_class = InMemoryRateLimiter
        else:
            resolved_class = registry[class_name]

    logger.info("Rate limiter [%s]: initializing with %s", namespace, resolved_class.__name__)
    instance = resolved_class(cap_per_minute, namespace)
    _rate_limiter_instances[namespace] = instance

    return instance


def get_rate_limiter(namespace: str) -> RateLimiter:
    """
    Get the rate limiter registered under the given namespace.

    If a BufferedRateLimiter was installed via `.buffered()`, that is returned
    transparently — callers need no awareness of buffering.

    Args:
        namespace (str): The namespace used during initialization (e.g. "sms").

    Returns:
        RateLimiter: The registered rate limiter instance.

    Raises:
        RuntimeError: If no limiter has been registered for this namespace.
    """
    instance = _rate_limiter_instances.get(namespace)
    if instance is None:
        raise RuntimeError(
            f"Rate limiter [{namespace!r}] not initialized. "
            "Call initialize_rate_limiter() during app startup (app/__init__.py)."
        )
    return instance


class RedisSlidingWindowLogRateLimiter(RateLimiter):
    """
    Redis-backed rate limiter using a sliding window log.

    Key structure:
    - ``app.rate_limit:{namespace}:{scope}:entries`` (sorted set)
      - Score: timestamp of when entry was added
      - Member: ``"entry_id:units"`` (unit count is encoded in the member)

    The default scope is ``"default"``; scoped views obtained via
    :meth:`for_scope` write to their own scope key. Unit counts are extracted
    by splitting on ``":"`` when needed.
    """

    WINDOW_SIZE_SECONDS = 60

    def __init__(self, cap_per_minute: int, namespace: str, redis_client=None, window_size: int = 60):
        """
        Initialize the Redis-backed rate limiter.

        Args:
            cap_per_minute (int): Maximum units allowed per minute.
            namespace (str): Logical name for this limiter instance (e.g. "sms").
                Used to construct the Redis key: app.rate_limit:{namespace}:{scope}:entries.
            redis_client: Redis client instance. If None, uses app's flask_cache_ops.
            window_size (int): Sliding window duration in seconds. Defaults to 60.
        """
        super().__init__(cap_per_minute, namespace)
        self.redis_client = redis_client
        self._lua_scripts: dict[str, object] = {}
        self.WINDOW_SIZE_SECONDS = window_size

    def _entries_key_for(self, scope: str = _DEFAULT_SCOPE) -> str:
        return f"app.rate_limit:{self.namespace}:{scope}:entries"

    @property
    def _entries_key(self) -> str:
        # Backward-compat alias for the default-scope key.
        return self._entries_key_for(_DEFAULT_SCOPE)

    @property
    def redis(self):
        # Lazy-load Redis client to avoid circular imports at init time.
        if self.redis_client is not None:
            return self.redis_client
        from app import flask_cache_ops

        return flask_cache_ops

    def _get_acquire_lua_script(self):
        if "acquire" not in self._lua_scripts:
            lua_code = """
            local entries_key = KEYS[1]

            local cap_per_minute = tonumber(ARGV[1])
            local units = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            local entry_id = ARGV[4]
            local window_size = tonumber(ARGV[5])

            local window_start = now - window_size

            -- 1. Remove expired entries
            redis.call('ZREMRANGEBYSCORE', entries_key, '-inf', '(' .. window_start)

            -- 2. Fetch all active entries with scores in a single call.
            --    Scores are timestamps; members encode units as "entry_id:units".
            --    This result is reused for both usage summation and wait-time
            --    calculation, avoiding a second ZRANGE on the denied path.
            local current_usage = 0
            local entries_with_scores = redis.call('ZRANGE', entries_key, 0, -1, 'WITHSCORES')

            for i = 1, #entries_with_scores, 2 do
                local member = entries_with_scores[i]
                local sep = string.find(member, ":")
                local entry_units = tonumber(string.sub(member, sep + 1)) or 0
                current_usage = current_usage + entry_units
            end

            -- 3. Check capacity
            if current_usage + units <= cap_per_minute then
                local member = entry_id .. ":" .. units

                redis.call('ZADD', entries_key, now, member)
                redis.call('EXPIRE', entries_key, window_size + 10)

                return {1, 0}
            else
                -- 4. Calculate wait time by iterating the already-fetched entries_with_scores.
                --    No second ZRANGE needed.
                local units_needed = current_usage + units - cap_per_minute
                local units_freed = 0
                local last_timestamp_to_wait = nil

                for i = 1, #entries_with_scores, 2 do
                    local member = entries_with_scores[i]
                    local timestamp = tonumber(entries_with_scores[i + 1])

                    local sep = string.find(member, ":")
                    local entry_units = tonumber(string.sub(member, sep + 1)) or 0
                    units_freed = units_freed + entry_units
                    last_timestamp_to_wait = timestamp

                    if units_freed >= units_needed then
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

    def acquire_lease(self, units: int = 1) -> Tuple[bool, int]:
        """Acquire capacity on the default scope. See :meth:`_acquire_lease_scoped`."""
        return self._acquire_lease_scoped(units, scope=_DEFAULT_SCOPE, cap_override=None)

    def _acquire_lease_scoped(self, units: int, *, scope: str, cap_override: int | None) -> Tuple[bool, int]:
        effective_cap = cap_override if cap_override is not None else self.cap_per_minute

        if units <= 0:
            raise ValueError("units must be positive")

        if units > effective_cap:
            raise ValueError("units must be smaller than or equal to the cap_per_minute")

        now = time()
        entry_id = str(uuid.uuid4())
        entries_key = self._entries_key_for(scope)

        script = self._get_acquire_lua_script()
        result = script(
            keys=[entries_key],
            args=[
                effective_cap,
                units,
                now,
                entry_id,
                self.WINDOW_SIZE_SECONDS,
            ],
        )

        success, wait_seconds = result[0], result[1]

        if success:
            _logger.debug(f"Rate limiter [{self.namespace}:{scope}]: acquired {units} units. Entry ID: {entry_id}")
        else:
            current_app.logger.warning(
                f"Rate limiter [{self.namespace}:{scope}]: capacity exhausted. Requested {units} units. "
                f"Will retry in {wait_seconds} seconds."
            )

        return bool(success), wait_seconds

    def get_current_usage(self) -> int:
        """Get the current unit count in the active window from Redis (default scope)."""
        return self._get_current_usage_scoped(scope=_DEFAULT_SCOPE)

    def _get_current_usage_scoped(self, *, scope: str) -> int:
        now = time()
        window_start = now - self.WINDOW_SIZE_SECONDS
        entries_key = self._entries_key_for(scope)

        # Read only the entries still inside the window without mutating the set.
        # The Lua acquire script removes entries with score < window_start (exclusive
        # upper bound), so an entry scored exactly at window_start is still live.
        # Use an inclusive lower bound here to match that semantics.
        current_usage = 0
        entries = self.redis.zrangebyscore(entries_key, window_start, "+inf")
        for member in entries:
            # Extract unit count from member string format "entry_id:units"
            if isinstance(member, bytes):
                member = member.decode("utf-8")
            units_str = member.split(":")[-1] if ":" in member else "0"
            try:
                current_usage += int(units_str)
            except ValueError:
                current_app.logger.warning(
                    f"Rate limiter [{self.namespace}:{scope}]: skipping malformed usage entry "
                    f"member={member!r}, units={units_str!r}"
                )

        return current_usage

    def reset_limiter(self):
        """Clear all scopes for this namespace."""
        pattern = f"app.rate_limit:{self.namespace}:*:entries"

        # Open a pipeline to delete all matching keys in a single round-trip.
        pipe = self.redis.pipeline()
        for key in self.redis.scan_iter(match=pattern):
            pipe.delete(key)
        pipe.execute()

        current_app.logger.info(f"Rate limiter [{self.namespace}]: entries cleared (all scopes)")

    def _reset_scoped(self, *, scope: str) -> None:
        self.redis.delete(self._entries_key_for(scope))
        current_app.logger.info(f"Rate limiter [{self.namespace}:{scope}]: entries cleared")


class RedisTokenBucketRateLimiter(RateLimiter):
    """
    Redis-backed rate limiter using a token bucket algorithm.

    Key structure:
    - ``app.rate_limit:{namespace}:{scope}:token_bucket`` (hash)
      - Field ``tokens``: current available capacity (float, stored as string)
      - Field ``last_refill``: timestamp of last refill (float, stored as string)

    Algorithm:
    - Tokens refill continuously at rate cap_per_minute / 60 per second.
    - On each request, elapsed time since last refill is computed, tokens are
      topped up (capped at max(1, cap_per_minute / 60)), and the requested units are
      subtracted atomically in Lua.
    - If tokens are insufficient, the exact wait time is returned:
      deficit / (max(1, cap_per_minute / 60)) seconds.
    - No burst after idle: the bucket ceiling is one second of capacity
      (max(1, cap_per_minute / 60)), so long idle periods never accumulate more than
      ~1 second worth of tokens. Maximum per-minute throughput cannot exceed
      cap_per_minute regardless of how long the system was idle.
    - Maximum units per acquire_lease call: max(1, cap_per_minute / 60) (one second).

    Scoping:
    Per-scope buckets are keyed by ``scope`` in the Redis key. Scoped views
    obtained via :meth:`for_scope` may also override the cap.

    Complexity: O(1) for all operations.
    """

    def __init__(self, cap_per_minute: int, namespace: str, redis_client=None):
        """
        Initialize the Redis token bucket rate limiter.

        Args:
            cap_per_minute (int): Maximum units allowed per minute.
            namespace (str): Logical name for this limiter instance (e.g. "sms").
                Used to construct the Redis key: app.rate_limit:{namespace}:{scope}:token_bucket.
            redis_client: Redis client instance. If None, uses app's flask_cache_ops.
        """
        super().__init__(cap_per_minute, namespace)
        self.redis_client = redis_client
        self._lua_scripts: dict[str, object] = {}

    def _bucket_key_for(self, scope: str = _DEFAULT_SCOPE) -> str:
        return f"app.rate_limit:{self.namespace}:{scope}:token_bucket"

    @property
    def _key(self) -> str:
        # Backward-compat alias for the default-scope key.
        return self._bucket_key_for(_DEFAULT_SCOPE)

    @property
    def max_units_per_acquire(self) -> int:
        """Per-call ceiling: one second of capacity, minimum 1."""
        return max(1, self.cap_per_minute // 60)

    def _max_units_for_cap(self, cap_override: int | None) -> int:
        effective_cap = cap_override if cap_override is not None else self.cap_per_minute
        return max(1, effective_cap // 60)

    @property
    def redis(self):
        # Lazy-load Redis client to avoid circular imports at init time.
        if self.redis_client is not None:
            return self.redis_client
        from app import flask_cache_ops

        return flask_cache_ops

    def _get_acquire_lua_script(self):
        if "acquire" not in self._lua_scripts:
            lua_code = """
            local key = KEYS[1]
            local cap = tonumber(ARGV[1])
            local units = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            local refill_rate = math.max(1, cap / 60.0)

            -- Read current state; initialize to one second of tokens on first call.
            -- Using refill_rate (not cap) as the starting value prevents burst-after-idle:
            -- a newly created or long-idle bucket holds at most one second of capacity.
            local tokens_str = redis.call('HGET', key, 'tokens')
            local last_refill_str = redis.call('HGET', key, 'last_refill')

            local tokens
            local last_refill
            if tokens_str == false then
                tokens = refill_rate
                last_refill = now
            else
                -- Default to 0 if tokens can't be parsed (defensive)
                tokens = tonumber(tokens_str) or 0
                last_refill = tonumber(last_refill_str) or now
            end

            -- Refill tokens based on elapsed time, capped at one second's worth.
            -- This keeps the maximum burst to ~1 second regardless of idle duration.
            local elapsed = now - last_refill
            tokens = math.min(refill_rate, tokens + elapsed * refill_rate)

            if tokens >= units then
                -- Admit: subtract units and persist new state
                tokens = tokens - units
                redis.call('HSET', key, 'tokens', tostring(tokens), 'last_refill', tostring(now))
                return {1, 0}
            else
                -- Reject: compute exact wait time
                local deficit = units - tokens
                local seconds_to_wait = math.ceil(deficit / refill_rate)
                seconds_to_wait = math.max(1, seconds_to_wait)
                -- Persist refreshed token count and timestamp even on reject
                redis.call('HSET', key, 'tokens', tostring(tokens), 'last_refill', tostring(now))
                return {0, seconds_to_wait}
            end
            """
            self._lua_scripts["acquire"] = self.redis.register_script(lua_code)

        return self._lua_scripts["acquire"]

    def acquire_lease(self, units: int = 1) -> Tuple[bool, int]:
        """Acquire capacity on the default scope. See :meth:`_acquire_lease_scoped`."""
        return self._acquire_lease_scoped(units, scope=_DEFAULT_SCOPE, cap_override=None)

    def _acquire_lease_scoped(self, units: int, *, scope: str, cap_override: int | None) -> Tuple[bool, int]:
        effective_cap = cap_override if cap_override is not None else self.cap_per_minute
        effective_max = self._max_units_for_cap(cap_override)

        if units <= 0:
            raise ValueError("units must be positive")

        if units > effective_max:
            raise ValueError(
                f"units ({units}) must be <= {effective_max} "
                f"(max(1, cap={effective_cap} // 60)). "
                "The bucket ceiling is one second of capacity to prevent burst."
            )

        now = time()
        key = self._bucket_key_for(scope)
        script = self._get_acquire_lua_script()
        result = script(
            keys=[key],
            args=[effective_cap, units, now],
        )

        success, wait_seconds = result[0], result[1]

        if success:
            _logger.debug(f"Rate limiter [{self.namespace}:{scope}]: acquired {units} units.")
        else:
            current_app.logger.warning(
                f"Rate limiter [{self.namespace}:{scope}]: capacity exhausted. Requested {units} units. "
                f"Will retry in {wait_seconds} seconds."
            )

        return bool(success), int(wait_seconds)

    def get_current_usage(self) -> int:
        """
        Get current consumed capacity equivalent on the default scope.

        Returns cap minus available tokens after applying any pending refill.
        This is a non-atomic read — do not rely on it for admission decisions.
        """
        return self._get_current_usage_scoped(scope=_DEFAULT_SCOPE)

    def _get_current_usage_scoped(self, *, scope: str) -> int:
        now = time()
        key = self._bucket_key_for(scope)
        tokens_str = self.redis.hget(key, "tokens")
        last_refill_str = self.redis.hget(key, "last_refill")

        if tokens_str is None or last_refill_str is None:
            return 0

        tokens = float(tokens_str if isinstance(tokens_str, str) else tokens_str.decode("utf-8"))
        last_refill = float(last_refill_str if isinstance(last_refill_str, str) else last_refill_str.decode("utf-8"))

        elapsed = now - last_refill
        refill_rate = max(1.0, self.cap_per_minute / 60.0)
        max_tokens = refill_rate  # ceiling matches Lua: one second of capacity
        tokens = min(max_tokens, tokens + elapsed * refill_rate)

        return max(0, round(max_tokens - tokens))

    def reset_limiter(self):
        """Clear all scopes for this namespace."""
        pattern = f"app.rate_limit:{self.namespace}:*:token_bucket"
        # Open a pipeline to delete all matching keys in a single round-trip.
        pipe = self.redis.pipeline()
        for key in self.redis.scan_iter(match=pattern):
            pipe.delete(key)
        pipe.execute()
        current_app.logger.info(f"Rate limiter [{self.namespace}]: reset (all scopes cleared)")

    def _reset_scoped(self, *, scope: str) -> None:
        self.redis.delete(self._bucket_key_for(scope))
        current_app.logger.info(f"Rate limiter [{self.namespace}:{scope}]: reset (token bucket)")


class BufferedRateLimiter(RateLimiter):
    """
    A buffering proxy that wraps any RateLimiter and pre-fetches tokens in
    configurable batches to reduce calls to the underlying backend (e.g. Redis).

    Each Celery worker process maintains its own local token counter. Tokens are
    spent locally without hitting the backend; the underlying limiter is only
    called when the local buffer runs dry.

    Token expiry:
    Each batch is stamped with ``_acquired_at``. Before spending local tokens,
    the buffer is checked for staleness: tokens older than 60 seconds are
    discarded. This prevents tokens from a previous rate-limit window from being
    consumed after the backend (especially a token bucket) has refilled, which
    would allow over-consumption up to ``size * num_workers`` beyond the cap.

    Top-up on partial buffer:
    When ``_local_tokens < units``, the buffer is topped up (not replaced).
    The underlying limiter is called for ``max(units - _local_tokens, size)``
    additional tokens. The existing local tokens are combined with the new
    batch, so already-claimed tokens are never wasted.

    Thread safety:
    Buffer state (``_local_tokens`` and ``_acquired_at``) is stored in a
    ``threading.local()`` so each thread maintains an independent token buffer,
    mirroring the one-buffer-per-worker isolation that prefork provided via
    separate processes.  The shared ``BufferedRateLimiter`` instance is held in
    the registry; only its buffer fields are thread-local.  The underlying
    backend (Redis) is already protected by atomic Lua scripts.
    """

    TOKEN_WINDOW_SECONDS = 60

    def __init__(self, rate_limiter: RateLimiter, size: int) -> None:
        if size <= 0:
            raise ValueError("size must be positive")
        if size > rate_limiter.max_units_per_acquire:
            raise ValueError(
                f"size ({size}) must be <= max_units_per_acquire ({rate_limiter.max_units_per_acquire}) "
                f"for {type(rate_limiter).__name__}"
            )
        super().__init__(rate_limiter.cap_per_minute, rate_limiter.namespace)
        self._rate_limiter = rate_limiter
        self._size = size
        self._local = threading.local()

    @property
    def _local_tokens(self) -> int:
        return getattr(self._local, "tokens", 0)

    @_local_tokens.setter
    def _local_tokens(self, value: int) -> None:
        self._local.tokens = value

    @property
    def _acquired_at(self) -> float:
        return getattr(self._local, "acquired_at", 0.0)

    @_acquired_at.setter
    def _acquired_at(self, value: float) -> None:
        self._local.acquired_at = value

    def acquire_lease(self, units: int = 1) -> Tuple[bool, int]:
        """
        Attempt to acquire a lease for the given number of units.

        Spends from the local buffer when possible. Tops up from the underlying
        rate limiter when the buffer is insufficient, fetching at least ``_size``
        tokens per Redis call.

        Args:
            units (int): Number of units to acquire. Defaults to 1.

        Returns:
            Tuple[bool, int]:
                - (True, 0) if units were acquired (locally or via the backend).
                - (False, seconds_to_wait) if the backend denied the request.
        """
        if units <= 0:
            raise ValueError("units must be positive")

        # Discard stale local tokens to prevent cross-window over-consumption.
        if self._local_tokens > 0 and time() - self._acquired_at >= self.TOKEN_WINDOW_SECONDS:
            _logger.debug(f"BufferedRateLimiter [{self.namespace}]: discarding {self._local_tokens} stale local tokens")
            self._local_tokens = 0

        # Fast path: if the local buffer has enough tokens, spend them without hitting the backend.
        if self._local_tokens >= units:
            self._local_tokens -= units
            _logger.debug(
                f"BufferedRateLimiter [{self.namespace}]: spent {units} local tokens " f"(remaining: {self._local_tokens})"
            )
            return True, 0

        # Top-up: fetch enough to cover the deficit, at least _size tokens.
        deficit = units - self._local_tokens
        batch = max(deficit, self._size)

        acquired, seconds_to_wait = self._rate_limiter.acquire_lease(batch)
        if not acquired:
            current_app.logger.warning(
                f"BufferedRateLimiter [{self.namespace}]: backend denied {batch} token batch. "
                f"Retry in {seconds_to_wait}s. Local buffer unchanged ({self._local_tokens} tokens)."
            )
            return False, seconds_to_wait

        self._acquired_at = time()
        self._local_tokens += batch
        self._local_tokens -= units
        _logger.debug(
            f"BufferedRateLimiter [{self.namespace}]: fetched {batch} tokens from backend, "
            f"spent {units}, local buffer now {self._local_tokens}"
        )
        return True, 0

    def get_current_usage(self) -> int:
        """Delegates to the wrapped rate limiter (reflects global consumed capacity)."""
        return self._rate_limiter.get_current_usage()


class ScopedRateLimiter(RateLimiter):
    """
    A lightweight scoped view of an underlying :class:`RateLimiter`.

    Obtained via :meth:`RateLimiter.for_scope`. Every operation delegates to the
    parent limiter through its ``_*_scoped`` hooks, narrowing state access to
    ``scope`` and optionally overriding the cap. The view holds no state of its
    own — each ``for_scope()`` call returns a new instance.

    Composition rules (enforced by the base class):
    - Cannot be buffered (``ScopedRateLimiter.buffered()`` raises ``TypeError``).
    - Cannot be scoped again (nested scoping is not supported).
    """

    def __init__(self, parent: RateLimiter, *, scope: str, cap_override: int | None = None) -> None:
        if not scope:
            raise ValueError("scope must be a non-empty string")
        if cap_override is not None and cap_override <= 0:
            raise ValueError("cap must be positive")
        effective_cap = cap_override if cap_override is not None else parent.cap_per_minute
        super().__init__(effective_cap, f"{parent.namespace}:{scope}")
        self._parent = parent
        self._scope = scope
        self._cap_override = cap_override

    @property
    def max_units_per_acquire(self) -> int:
        return self._parent._max_units_for_cap(self._cap_override)

    def acquire_lease(self, units: int = 1) -> Tuple[bool, int]:
        return self._parent._acquire_lease_scoped(units, scope=self._scope, cap_override=self._cap_override)

    def get_current_usage(self) -> int:
        return self._parent._get_current_usage_scoped(scope=self._scope)

    def reset_limiter(self) -> None:
        self._parent._reset_scoped(scope=self._scope)
