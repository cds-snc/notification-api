"""
Scaling benchmark: RedisZSetRateLimiter vs RedisTokenBucketRateLimiter.

Measures how acquire_lease() time changes as the number of pre-existing
ZSet entries grows.  The token bucket is O(1) and unaffected by history;
the ZSet implementation is O(N) and should grow linearly.

Run explicitly with:
    pytest tests/app/test_rate_limiter_scaling.py -v -s -m scaling
"""

import time

import fakeredis
import pytest

from app.rate_limiter import RedisTokenBucketRateLimiter, RedisZSetRateLimiter

# N values to sweep. Each represents the number of prior entries in the
# ZSet window before the timed call.
N_VALUES = [1, 10, 50, 100, 250, 500, 750, 1000]

# Repetitions per N value -- averaged to reduce noise.
REPS = 20

# Cap large enough that pre-filling N entries (1 part each) never hits it.
CAP = N_VALUES[-1] * 2 + REPS


def _prefill_zset(limiter: RedisZSetRateLimiter, n: int) -> None:
    """Add n entries (1 part each) at staggered fake timestamps so none expire."""
    base = time.time()
    for i in range(n):
        # Spread entries across the 60 s window so none are cleaned on admit
        fake_now = base - 59.0 + (59.0 / max(n, 1)) * i
        limiter._get_acquire_lua_script()(
            keys=[limiter.REDIS_KEY_ENTRIES],
            args=[CAP, 1, fake_now, f"prefill-{i}", limiter.WINDOW_SIZE_SECONDS],
        )


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
    Print a timing table comparing ZSet (O(N)) vs token bucket (O(1))
    as the number of pre-existing entries grows.
    """
    rows = []

    with client.application.app_context():
        for n in N_VALUES:
            # ---- ZSet ----
            zset_redis = fakeredis.FakeRedis()
            zset = RedisZSetRateLimiter(cap_per_minute=CAP, redis_client=zset_redis)
            _prefill_zset(zset, n)
            zset_us = _time_acquire(zset, REPS)

            # ---- Token bucket ----
            tb_redis = fakeredis.FakeRedis()
            tb = RedisTokenBucketRateLimiter(cap_per_minute=CAP, redis_client=tb_redis)
            tb_us = _time_acquire(tb, REPS)

            ratio = zset_us / tb_us if tb_us > 0 else float("inf")
            rows.append((n, zset_us, tb_us, ratio))

    # Print table
    header = f"\n{'N entries':>10}  {'ZSet (us)':>12}  {'TokenBucket (us)':>18}  {'ratio (ZSet/TB)':>16}"
    separator = "-" * len(header)
    print(header)
    print(separator)
    for n, zset_us, tb_us, ratio in rows:
        print(f"{n:>10}  {zset_us:>12.1f}  {tb_us:>18.1f}  {ratio:>16.2f}x")

    # Soft assertion: ZSet at max N should be slower than token bucket.
    # This confirms O(N) vs O(1) divergence is observable even in fakeredis.
    _, zset_max, tb_max, _ = rows[-1]
    assert zset_max > tb_max, (
        f"Expected ZSet to be slower than token bucket at N={N_VALUES[-1]}, "
        f"but ZSet={zset_max:.1f}us, TokenBucket={tb_max:.1f}us"
    )
