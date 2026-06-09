"""
Scaling benchmark: RedisSlidingWindowLogRateLimiter vs RedisTokenBucketRateLimiter vs InMemoryRateLimiter.

Measures how acquire_lease() time changes as the number of pre-existing
entries grows.  The sliding window log is O(N); the token bucket and
in-memory admit path are O(1) and unaffected by history size.

Run explicitly with:
    pytest tests/app/test_rate_limiter_scaling.py -v -s -m scaling
"""

import time
from unittest.mock import patch

import fakeredis
import pytest

from app.rate_limiter import InMemoryRateLimiter, RedisSlidingWindowLogRateLimiter, RedisTokenBucketRateLimiter

# N values to sweep. Each represents the number of prior entries in the
# window before the timed call.
N_VALUES = [1, 10, 50, 100, 250, 500, 750, 1000]

# Repetitions per N value -- averaged to reduce noise.
REPS = 20

# Cap large enough that pre-filling N entries (1 part each) never hits it.
CAP = N_VALUES[-1] * 2 + REPS


def _prefill_zset(limiter: RedisSlidingWindowLogRateLimiter, n: int) -> None:
    """Add n entries (1 part each) at staggered fake timestamps so none expire."""
    base = time.time()
    for i in range(n):
        # Spread entries across the 60 s window so none are cleaned on admit
        fake_now = base - 59.0 + (59.0 / max(n, 1)) * i
        limiter._get_acquire_lua_script()(
            keys=[limiter.REDIS_KEY_ENTRIES],
            args=[CAP, 1, fake_now, f"prefill-{i}", limiter.WINDOW_SIZE_SECONDS],
        )


def _prefill_in_memory(limiter: InMemoryRateLimiter, n: int) -> None:
    """Fill the deque with n entries by calling acquire_lease() n times at a fixed timestamp."""
    fixed_time = time.time()
    with patch("app.rate_limiter.time", return_value=fixed_time):
        for _ in range(n):
            limiter.acquire_lease(1)


def _time_acquire(limiter, reps: int) -> float:
    """Return mean us for acquire_lease(1) over reps calls."""
    total = 0.0
    for _ in range(reps):
        t0 = time.perf_counter()
        limiter.acquire_lease(1)
        total += time.perf_counter() - t0
    return (total / reps) * 1_000_000  # us


@pytest.mark.scaling
def test_scaling_comparison(client):
    """
    Print a timing table comparing all three implementations as prior entry
    count grows.  Only the sliding window log is O(N); the other two are O(1).

    Note: in-memory has no Redis overhead, so its absolute numbers are lower
    than the Redis implementations -- compare slopes, not absolute values.
    """
    rows = []

    with client.application.app_context():
        for n in N_VALUES:
            # ---- ZSet ----
            zset_redis = fakeredis.FakeRedis()
            zset = RedisSlidingWindowLogRateLimiter(cap_per_minute=CAP, redis_client=zset_redis)
            _prefill_zset(zset, n)
            zset_us = _time_acquire(zset, REPS)

            # ---- Token bucket (Redis hash) ----
            tb_redis = fakeredis.FakeRedis()
            tb = RedisTokenBucketRateLimiter(cap_per_minute=CAP, redis_client=tb_redis)
            tb_us = _time_acquire(tb, REPS)

            # ---- In-memory (deque, process-local baseline) ----
            mem = InMemoryRateLimiter(cap_per_minute=CAP)
            _prefill_in_memory(mem, n)
            mem_us = _time_acquire(mem, REPS)

            rows.append((n, zset_us, tb_us, mem_us))

    # Print table
    header = (
        f"\n{'N entries':>10}  {'SlidingLog (us)':>16}  "
        f"{'TokenBucket (us)':>16}  {'InMemory (us)':>14}  {'ratio (Log/TB)':>14}"
    )
    separator = "-" * len(header)
    print(header)
    print(separator)
    for n, zset_us, tb_us, mem_us in rows:
        ratio = zset_us / tb_us if tb_us > 0 else float("inf")
        print(f"{n:>10}  {zset_us:>16.1f}  {tb_us:>16.1f}  {mem_us:>14.1f}  {ratio:>14.2f}x")

    # Soft assertion: sliding window log at max N should be slower than token bucket.
    # This confirms O(N) vs O(1) divergence is observable even in fakeredis.
    _, zset_max, tb_max, _ = rows[-1]
    assert zset_max > tb_max, (
        f"Expected sliding window log to be slower than token bucket at N={N_VALUES[-1]}, "
        f"but SlidingLog={zset_max:.1f}us, TokenBucket={tb_max:.1f}us"
    )
