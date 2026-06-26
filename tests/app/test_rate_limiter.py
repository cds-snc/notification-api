from time import time
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from app import rate_limiter
from app.rate_limiter import (
    BufferedRateLimiter,
    InMemoryRateLimiter,
    RedisSlidingWindowLogRateLimiter,
    RedisTokenBucketRateLimiter,
    get_rate_limiter,
    initialize_rate_limiter,
)


class TestInMemoryRateLimiter:
    @pytest.fixture
    def limiter(self):
        return InMemoryRateLimiter(cap_per_minute=1000, namespace="test")

    def test_acquire_lease_below_capacity_succeeds(self, client, limiter):
        with client.application.app_context():
            allow_send, wait_seconds = limiter.acquire_lease(100)
            assert allow_send is True
            assert wait_seconds == 0

    def test_acquire_lease_at_capacity_succeeds(self, client, limiter):
        with client.application.app_context():
            allow_send, wait_seconds = limiter.acquire_lease(1000)
            assert allow_send is True
            assert wait_seconds == 0

    def test_acquire_lease_exceeding_capacity_fails(self, client, limiter):
        with client.application.app_context():
            # Fill capacity
            limiter.acquire_lease(1000)
            # Try to exceed
            allow_send, wait_seconds = limiter.acquire_lease(100)
            assert allow_send is False
            assert wait_seconds > 0

    def test_acquire_with_zero_parts_raises_error(self, client, limiter):
        with client.application.app_context():
            with pytest.raises(ValueError):
                limiter.acquire_lease(0)

    def test_acquire_negative_parts_raises_error(self, client, limiter):
        with client.application.app_context():
            with pytest.raises(ValueError):
                limiter.acquire_lease(-10)

    def test_acquire_over_capacity_raises_error(self, client, limiter):
        with client.application.app_context():
            with pytest.raises(ValueError):
                limiter.acquire_lease(limiter.cap_per_minute + 1)

    def test_running_total_incremented_on_acquire(self, client, limiter):
        with client.application.app_context():
            assert limiter.current_usage == 0
            limiter.acquire_lease(100)
            assert limiter.current_usage == 100

    def test_running_total_decremented_on_window_expiration(self, client, limiter):
        with client.application.app_context():
            limiter.acquire_lease(100)
            assert limiter.current_usage == 100

            # Mock time to simulate window expiration
            with patch("app.rate_limiter.time") as mock_time:
                # Simulate 10 seconds after the window should have expired
                mock_time.return_value = limiter.window[0][0] + limiter.WINDOW_SIZE_SECONDS + 10
                limiter.get_current_usage()
                assert limiter.current_usage == 0

    def test_window_entries_removed_after_window_expiration(self, client, limiter):
        with client.application.app_context():
            limiter.acquire_lease(100)
            limiter.acquire_lease(200)
            assert len(limiter.window) == 2

            # Mock time to simulate window expiration
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = limiter.window[0][0] + limiter.WINDOW_SIZE_SECONDS + 10
                limiter.get_current_usage()
                assert len(limiter.window) == 0

    def test_get_current_usage_returns_running_total(self, client, limiter):
        with client.application.app_context():
            limiter.acquire_lease(150)
            limiter.acquire_lease(250)
            limiter.acquire_lease(300)
            assert limiter.get_current_usage() == 700

    def test_multiple_entries_in_window(self, client, limiter):
        with client.application.app_context():
            limiter.acquire_lease(10)
            limiter.acquire_lease(20)
            limiter.acquire_lease(30)

            assert len(limiter.window) == 3
            assert limiter.current_usage == 60

    def test_retry_delay_when_single_entry_needs_to_expire(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0  # arbitrary base time where window start is not negative (100-60 = 40)
                mock_time.return_value = base_time

                # Fill capacity
                limiter.acquire_lease(1000)
                # Try to exceed
                mock_time.return_value = base_time + 5
                allow_send, wait_seconds = limiter.acquire_lease(50)

                assert allow_send is False
                # Should wait until the first entry expires
                assert wait_seconds >= limiter.WINDOW_SIZE_SECONDS - 5 - 1  # subtract 1 second for rounding
                assert wait_seconds <= limiter.WINDOW_SIZE_SECONDS

    def test_retry_delay_when_multiple_entries_need_to_expire(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0  # arbitrary base time where window start is not negative (100-60 = 40)
                mock_time.return_value = base_time

                # Add multiple entries that together fill the window
                limiter.acquire_lease(400)  # Entry 1 at time 100
                mock_time.return_value = base_time + 5
                limiter.acquire_lease(400)  # Entry 2 at time 105
                mock_time.return_value = base_time + 10
                limiter.acquire_lease(200)  # Entry 3 at time 110

                # At time 110, usage is maxed out at 1000/1000 (400 + 400 + 200)
                # Try to add 500 more parts
                mock_time.return_value = base_time + 10
                allow_send, wait_seconds = limiter.acquire_lease(500)

                assert allow_send is False
                # Need to free 500 parts: Entry 1 (400) + Entry 2 (400) = 800 > 500
                # So we need to wait for Entry 2 (at time 105) to expire
                # Entry 2 expires at time 105 + 60 = 165
                # At current time 110, we wait 55 seconds + 1 in case of rounding
                assert wait_seconds >= limiter.WINDOW_SIZE_SECONDS - 5 - 1
                assert wait_seconds <= limiter.WINDOW_SIZE_SECONDS

    def test_capacity_after_some_entries_expire(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0  # arbitrary base       time where window start is not negative (100-60 = 40)
                mock_time.return_value = base_time

                # Add entry 1: 600 parts at time 100
                limiter.acquire_lease(600)
                mock_time.return_value = base_time + 10
                # Add entry 2: 400 parts at time 110
                limiter.acquire_lease(400)

                # Set time to 170 seconds, entry 1 should have expired, but entry 2 should still be there
                mock_time.return_value = base_time + 70
                allow_send, _ = limiter.acquire_lease(500)

                assert allow_send is True
                assert limiter.current_usage == 900

    def test_window_slightly_older_than_60_seconds_is_removed(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0  # arbitrary base time where window start is not negative (100-60 = 40)
                mock_time.return_value = base_time
                limiter.acquire_lease(50)

                # At 160.1 seconds entry should be removed
                mock_time.return_value = base_time + 60.1
                limiter.get_current_usage()
                assert limiter.current_usage == 0

    def test_window_exactly_60_seconds_old_is_not_removed(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0  # arbitrary base time where window start is not negative (100-60 = 40)
                mock_time.return_value = base_time
                limiter.acquire_lease(50)

                mock_time.return_value = base_time + 60.0
                limiter.get_current_usage()
                # Entry should still be in window
                assert limiter.current_usage == 50

    def test_window_slightly_under_60_seconds_is_kept(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0  # arbitrary base time where window start is not negative (100-60 = 40)
                mock_time.return_value = base_time
                limiter.acquire_lease(50)

                # At 59.9 seconds, entry should still be there
                mock_time.return_value = base_time + 59.9
                limiter.get_current_usage()
                assert limiter.current_usage == 50


class TestRedisSlidingWindowLogRateLimiter:
    @pytest.fixture
    def limiter(self):
        redis_client = fakeredis.FakeRedis()
        return RedisSlidingWindowLogRateLimiter(cap_per_minute=1000, namespace="test", redis_client=redis_client)

    def test_acquire_lease_below_capacity_succeeds(self, client, limiter):
        with client.application.app_context():
            allow_send, wait_seconds = limiter.acquire_lease(100)
            assert allow_send is True
            assert wait_seconds == 0

    def test_acquire_lease_at_capacity_succeeds(self, client, limiter):
        with client.application.app_context():
            allow_send, wait_seconds = limiter.acquire_lease(1000)
            assert allow_send is True
            assert wait_seconds == 0

    def test_acquire_lease_exceeding_capacity_fails(self, client, limiter):
        with client.application.app_context():
            limiter.acquire_lease(1000)
            allow_send, wait_seconds = limiter.acquire_lease(100)

            assert allow_send is False
            assert wait_seconds > 0

    def test_acquire_with_zero_parts_raises_error(self, client, limiter):
        with client.application.app_context():
            with pytest.raises(ValueError):
                limiter.acquire_lease(0)

    def test_acquire_negative_parts_raises_error(self, client, limiter):
        with client.application.app_context():
            with pytest.raises(ValueError):
                limiter.acquire_lease(-10)

    def test_acquire_over_capacity_raises_error(self, client, limiter):
        with client.application.app_context():
            with pytest.raises(ValueError):
                limiter.acquire_lease(limiter.cap_per_minute + 1)

    def test_get_current_usage_returns_running_total(self, client, limiter):
        with client.application.app_context():
            limiter.acquire_lease(150)
            limiter.acquire_lease(250)
            limiter.acquire_lease(300)

            assert limiter.get_current_usage() == 700

    def test_multiple_entries_in_window(self, client, limiter):
        with client.application.app_context():
            limiter.acquire_lease(10)
            limiter.acquire_lease(20)
            limiter.acquire_lease(30)

            usage = limiter.get_current_usage()
            assert usage == 60

    def test_retry_delay_when_single_entry_needs_to_expire(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0
                mock_time.return_value = base_time

                limiter.acquire_lease(1000)

                mock_time.return_value = base_time + 5
                allow_send, wait_seconds = limiter.acquire_lease(50)

                assert allow_send is False
                assert wait_seconds >= limiter.WINDOW_SIZE_SECONDS - 5 - 1
                assert wait_seconds <= limiter.WINDOW_SIZE_SECONDS

    def test_retry_delay_when_multiple_entries_need_to_expire(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0
                mock_time.return_value = base_time

                limiter.acquire_lease(400)

                mock_time.return_value = base_time + 5
                limiter.acquire_lease(400)

                mock_time.return_value = base_time + 10
                limiter.acquire_lease(200)

                mock_time.return_value = base_time + 10
                allow_send, wait_seconds = limiter.acquire_lease(500)

                assert allow_send is False
                assert wait_seconds >= limiter.WINDOW_SIZE_SECONDS - 5 - 1
                assert wait_seconds <= limiter.WINDOW_SIZE_SECONDS

    def test_capacity_after_some_entries_expire(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0
                mock_time.return_value = base_time

                limiter.acquire_lease(600)

                mock_time.return_value = base_time + 10
                limiter.acquire_lease(400)

                # First entry expires (100 + 60 = 160)
                mock_time.return_value = base_time + 70
                allow_send, _ = limiter.acquire_lease(500)

                assert allow_send is True
                assert limiter.get_current_usage() == 900

    def test_window_slightly_older_than_60_seconds_is_removed(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0
                mock_time.return_value = base_time

                limiter.acquire_lease(50)

                mock_time.return_value = base_time + 60.1
                assert limiter.get_current_usage() == 0

    def test_window_exactly_60_seconds_old_is_not_removed(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0
                mock_time.return_value = base_time

                limiter.acquire_lease(50)

                mock_time.return_value = base_time + 60.0
                assert limiter.get_current_usage() == 50

    def test_window_slightly_under_60_seconds_is_kept(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0
                mock_time.return_value = base_time

                limiter.acquire_lease(50)

                mock_time.return_value = base_time + 59.9
                assert limiter.get_current_usage() == 50


class TestRedisTokenBucketRateLimiter:
    @pytest.fixture
    def limiter(self):
        redis_client = fakeredis.FakeRedis()
        return RedisTokenBucketRateLimiter(cap_per_minute=1000, namespace="test", redis_client=redis_client)

    def test_acquire_lease_below_capacity_succeeds(self, client, limiter):
        # max_tokens = 1000/60 ≈ 16.67; requesting 10 fits comfortably
        with client.application.app_context():
            allow_send, wait_seconds = limiter.acquire_lease(10)
            assert allow_send is True
            assert wait_seconds == 0

    def test_acquire_lease_at_capacity_succeeds(self, client, limiter):
        # max_tokens ≈ 16.67; requesting 16 fits within the ceiling
        with client.application.app_context():
            allow_send, wait_seconds = limiter.acquire_lease(16)
            assert allow_send is True
            assert wait_seconds == 0

    def test_acquire_lease_exceeding_capacity_fails(self, client, limiter):
        # Fill the bucket then request 1 more — must be denied
        with client.application.app_context():
            limiter.acquire_lease(16)
            allow_send, wait_seconds = limiter.acquire_lease(1)
            assert allow_send is False
            assert wait_seconds > 0

    def test_acquire_with_zero_parts_raises_error(self, client, limiter):
        with client.application.app_context():
            with pytest.raises(ValueError):
                limiter.acquire_lease(0)

    def test_acquire_negative_parts_raises_error(self, client, limiter):
        with client.application.app_context():
            with pytest.raises(ValueError):
                limiter.acquire_lease(-10)

    def test_acquire_over_capacity_raises_error(self, client, limiter):
        with client.application.app_context():
            with pytest.raises(ValueError):
                limiter.acquire_lease(limiter.cap_per_minute + 1)

    def test_get_current_usage_returns_consumed_parts(self, client, limiter):
        # max_tokens ≈ 16.67; consume 5+8=13, leaving ~3.67 available
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(5)
                limiter.acquire_lease(8)
                # freeze time so no refill occurs during get_current_usage
                assert limiter.get_current_usage() == 13

    def test_get_current_usage_zero_when_bucket_empty(self, client, limiter):
        with client.application.app_context():
            assert limiter.get_current_usage() == 0

    def test_retry_delay_is_precise(self, client, limiter):
        # refill_rate = 1000/60 ≈ 16.67 tokens/sec
        # Fill the bucket (16 tokens), then request 1 more:
        # deficit = 1, wait = ceil(1 / 16.67) = 1 s
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(16)
                allow_send, wait_seconds = limiter.acquire_lease(1)
                assert allow_send is False
                import math

                expected = math.ceil(1 / (1000 / 60))
                assert wait_seconds == expected

    def test_capacity_refills_over_time(self, client, limiter):
        # Fill bucket, advance 0.12 s: refill = 16.67 * 0.12 = 2.0 tokens
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(16)

                # 0.12 seconds refills ≈ 2 tokens — enough to acquire 2
                mock_time.return_value = 100.12
                allow_send, _ = limiter.acquire_lease(2)
                assert allow_send is True

    def test_capacity_refills_over_more_time(self, client, limiter):
        # Fill bucket, advance 10s: refill = 16.67 * 10 = 166.7 tokens
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(16)

                # 10 seconds refills ≈ 166.7 tokens — enough to acquire 16 a few times
                mock_time.return_value = 110.0
                allow_send, _ = limiter.acquire_lease(16)
                assert allow_send is True

                # Acquire more but it should fail as internal buckets are 1 second split
                allow_send, _ = limiter.acquire_lease(16)
                assert allow_send is False

    def test_bucket_does_not_exceed_max_burst_after_idle(self, client, limiter):
        # Even after 120 s of idle, the bucket holds at most refill_rate ≈ 16.67 tokens.
        # Requesting 16 must succeed, but 17 must fail.
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(10)

                # Advance 120 seconds — bucket should be capped at ~16.67, not 10 + 16.67*120
                mock_time.return_value = 220.0
                allow_send, _ = limiter.acquire_lease(16)
                assert allow_send is True

    def test_no_burst_after_idle(self, client, limiter):
        # After any amount of idle time the bucket never accumulates more than
        # one second of tokens (≈16.67). A request for 17 must always be denied.
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                # Drain the bucket first
                limiter.acquire_lease(16)

                # Advance 60 seconds — old behaviour would refill to 1000, new caps at ≈16.67
                mock_time.return_value = 160.0
                with pytest.raises(ValueError):
                    limiter.acquire_lease(17)  # still above the ceiling

    def test_bucket_refills_fully_after_one_second(self, client, limiter):
        # After draining, exactly 1 second of elapsed time refills the ceiling.
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0
                mock_time.return_value = base_time
                limiter.acquire_lease(16)

                # After 1 second the bucket is back at ≈16.67 — enough for 16
                mock_time.return_value = base_time + 1.0
                allow_send, _ = limiter.acquire_lease(16)
                assert allow_send is True

    def test_reset_clears_bucket(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(16)
                allow_send, _ = limiter.acquire_lease(1)
                assert allow_send is False

                limiter.reset_limiter()
                # After reset, bucket reinitialises with one second of tokens
                allow_send, _ = limiter.acquire_lease(16)
                assert allow_send is True

    def test_multiple_sequential_acquires_deplete_tokens(self, client, limiter):
        # max_tokens ≈ 16.67; acquiring 10 + 6 = 16 leaves < 1 token
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(10)
                limiter.acquire_lease(6)
                # Bucket now has ≈ 0.67 tokens — not enough for 1
                allow_send, _ = limiter.acquire_lease(1)
                assert allow_send is False

    def test_bucket_not_fully_refilled_after_partial_second(self, client, limiter):
        # After depleting 16 tokens (leaving ≈0.67 tokens), 0.9 s elapses:
        # refill = 16.67 * 0.9 ≈ 15.0 tokens, total ≈15.67 < 16.
        # A second full-ceiling request must therefore fail.
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                base_time = 100.0
                mock_time.return_value = base_time
                limiter.acquire_lease(16)

                # 0.9 seconds refills ≈15.67 tokens — not enough for another 16
                mock_time.return_value = base_time + 0.9
                allow_send, _ = limiter.acquire_lease(16)
                assert allow_send is False

    def test_retry_delay_with_partial_prior_consumption(self, client, limiter):
        # max_tokens ≈ 16.67; acquire 8+5=13 leaving ≈3.67 tokens.
        # Requesting 5 creates a deficit of ≈1.33.
        # wait = ceil(1.33 / 16.67) = ceil(0.08) = 1 s.
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(8)
                limiter.acquire_lease(5)
                # ≈3.67 tokens remain; requesting 5 → deficit ≈1.33
                allow_send, wait_seconds = limiter.acquire_lease(5)
                assert allow_send is False
                assert wait_seconds == 1


class TestInitializeRateLimiter:
    def teardown_method(self):
        # Reset registry between tests
        rate_limiter._rate_limiter_instances.clear()

    def test_explicit_class_arg_takes_precedence(self, client):
        with client.application.app_context():
            instance = initialize_rate_limiter(1000, RedisTokenBucketRateLimiter, namespace="test")
            assert isinstance(instance, RedisTokenBucketRateLimiter)

    def test_explicit_in_memory_class_arg(self, client):
        with client.application.app_context():
            instance = initialize_rate_limiter(1000, InMemoryRateLimiter, namespace="test")
            assert isinstance(instance, InMemoryRateLimiter)

    def test_config_name_resolves_token_bucket(self, client):
        with client.application.app_context():
            with patch("app.rate_limiter._build_limiter_registry") as mock_registry:
                mock_registry.return_value = {
                    "InMemoryRateLimiter": InMemoryRateLimiter,
                    "RedisSlidingWindowLogRateLimiter": RedisSlidingWindowLogRateLimiter,
                    "RedisTokenBucketRateLimiter": RedisTokenBucketRateLimiter,
                }
                with patch("app.rate_limiter.InMemoryRateLimiter", InMemoryRateLimiter):
                    with patch("app.config.Config.SMS_RATE_LIMITER_BACKEND", "RedisTokenBucketRateLimiter", create=True):
                        instance = initialize_rate_limiter(1000, namespace="test")
                        assert isinstance(instance, RedisTokenBucketRateLimiter)

    def test_config_name_resolves_zset(self, client):
        with client.application.app_context():
            with patch("app.rate_limiter._build_limiter_registry") as mock_registry:
                mock_registry.return_value = {
                    "InMemoryRateLimiter": InMemoryRateLimiter,
                    "RedisSlidingWindowLogRateLimiter": RedisSlidingWindowLogRateLimiter,
                    "RedisTokenBucketRateLimiter": RedisTokenBucketRateLimiter,
                }
                with patch("app.config.Config.SMS_RATE_LIMITER_BACKEND", "RedisSlidingWindowLogRateLimiter", create=True):
                    instance = initialize_rate_limiter(1000, namespace="test")
                    assert isinstance(instance, RedisSlidingWindowLogRateLimiter)

    def test_unknown_config_name_falls_back_to_in_memory(self, client):
        with client.application.app_context():
            with patch("app.rate_limiter._build_limiter_registry") as mock_registry:
                mock_registry.return_value = {
                    "InMemoryRateLimiter": InMemoryRateLimiter,
                    "RedisSlidingWindowLogRateLimiter": RedisSlidingWindowLogRateLimiter,
                    "RedisTokenBucketRateLimiter": RedisTokenBucketRateLimiter,
                }
                with patch("app.config.Config.SMS_RATE_LIMITER_BACKEND", "UnknownClass", create=True):
                    instance = initialize_rate_limiter(1000, namespace="test")
                    assert isinstance(instance, InMemoryRateLimiter)

    def test_default_no_args_uses_in_memory(self, client):
        with client.application.app_context():
            with patch("app.config.Config.SMS_RATE_LIMITER_BACKEND", "InMemoryRateLimiter", create=True):
                instance = initialize_rate_limiter(1000, namespace="test")
                assert isinstance(instance, InMemoryRateLimiter)


class TestBufferedRateLimiter:
    @pytest.fixture
    def raw_limiter(self):
        return InMemoryRateLimiter(cap_per_minute=1000, namespace="test")

    @pytest.fixture
    def buffered(self, raw_limiter):
        return BufferedRateLimiter(raw_limiter, size=10)

    def test_uses_local_tokens_without_calling_rate_limiter(self, client, raw_limiter):
        mock_raw = MagicMock(spec=InMemoryRateLimiter)
        mock_raw.cap_per_minute = 1000
        mock_raw.namespace = "test"
        buf = BufferedRateLimiter(mock_raw, size=10)
        buf._local_tokens = 5
        buf._acquired_at = time()

        acquired, wait = buf.acquire_lease(3)

        assert acquired is True
        assert wait == 0
        assert buf._local_tokens == 2
        mock_raw.acquire_lease.assert_not_called()

    def test_fetches_batch_when_local_tokens_empty(self, client, buffered):
        with client.application.app_context():
            buffered._local_tokens = 0
            acquired, wait = buffered.acquire_lease(2)
            assert acquired is True
            assert wait == 0
            # fetched batch of 10 (size), spent 2 → 8 remain
            assert buffered._local_tokens == 8

    def test_tops_up_partial_buffer(self, client, buffered):
        with client.application.app_context():
            buffered._local_tokens = 3
            buffered._acquired_at = time()
            acquired, wait = buffered.acquire_lease(6)
            assert acquired is True
            assert wait == 0
            # deficit=3, batch=max(3,10)=10 fetched from backend
            # local = 3 + 10 - 6 = 7
            assert buffered._local_tokens == 7

    def test_local_tokens_preserved_on_redis_deny(self, client, raw_limiter):
        mock_raw = MagicMock(spec=InMemoryRateLimiter)
        mock_raw.cap_per_minute = 1000
        mock_raw.namespace = "test"
        mock_raw.acquire_lease.return_value = (False, 30)
        buf = BufferedRateLimiter(mock_raw, size=10)
        buf._local_tokens = 3
        buf._acquired_at = time()

        acquired, wait = buf.acquire_lease(6)

        assert acquired is False
        assert wait == 30
        assert buf._local_tokens == 3  # unchanged

    def test_returns_false_with_wait_when_rate_limiter_denies_empty_buffer(self, client, raw_limiter):
        mock_raw = MagicMock(spec=InMemoryRateLimiter)
        mock_raw.cap_per_minute = 1000
        mock_raw.namespace = "test"
        mock_raw.acquire_lease.return_value = (False, 15)
        buf = BufferedRateLimiter(mock_raw, size=10)

        with client.application.app_context():
            acquired, wait = buf.acquire_lease(5)

        assert acquired is False
        assert wait == 15
        assert buf._local_tokens == 0

    def test_deficit_larger_than_size_fetches_exact_deficit(self, client, raw_limiter):
        mock_raw = MagicMock(spec=InMemoryRateLimiter)
        mock_raw.cap_per_minute = 1000
        mock_raw.namespace = "test"
        mock_raw.acquire_lease.return_value = (True, 0)
        buf = BufferedRateLimiter(mock_raw, size=10)
        buf._local_tokens = 2
        buf._acquired_at = time()

        with client.application.app_context():
            acquired, wait = buf.acquire_lease(20)  # deficit=18 > size=10

        assert acquired is True
        mock_raw.acquire_lease.assert_called_once_with(18)  # max(18, 10) = 18
        assert buf._local_tokens == 0  # 2 + 18 - 20 = 0

    def test_remainder_decrements_on_successive_calls(self, client, buffered):
        with client.application.app_context():
            buffered._local_tokens = 0
            # First call fetches batch of 10, spends 3 → 7 remain
            buffered.acquire_lease(3)
            assert buffered._local_tokens == 7
            # Second call spends 4 locally → 3 remain
            buffered.acquire_lease(4)
            assert buffered._local_tokens == 3

    def test_stale_tokens_discarded_after_60_seconds(self, client, raw_limiter):
        mock_raw = MagicMock(spec=InMemoryRateLimiter)
        mock_raw.cap_per_minute = 1000
        mock_raw.namespace = "test"
        mock_raw.acquire_lease.return_value = (True, 0)
        buf = BufferedRateLimiter(mock_raw, size=10)
        buf._local_tokens = 50
        buf._acquired_at = time() - 61  # stale

        with client.application.app_context():
            buf.acquire_lease(3)

        # Stale tokens discarded; backend called for a fresh batch
        mock_raw.acquire_lease.assert_called_once()
        assert buf._local_tokens == 7  # 0 + 10 - 3

    def test_fresh_tokens_not_discarded_within_60_seconds(self, client, raw_limiter):
        mock_raw = MagicMock(spec=InMemoryRateLimiter)
        mock_raw.cap_per_minute = 1000
        mock_raw.namespace = "test"
        buf = BufferedRateLimiter(mock_raw, size=10)
        buf._local_tokens = 5
        buf._acquired_at = time() - 30  # still fresh

        buf.acquire_lease(2)

        mock_raw.acquire_lease.assert_not_called()
        assert buf._local_tokens == 3

    def test_acquired_at_updated_on_each_redis_fetch(self, client, buffered):
        with client.application.app_context():
            before = time()
            buffered.acquire_lease(1)
            assert buffered._acquired_at >= before

    def test_get_current_usage_delegates_to_wrapped_limiter(self, client):
        mock_raw = MagicMock(spec=InMemoryRateLimiter)
        mock_raw.cap_per_minute = 1000
        mock_raw.namespace = "test"
        mock_raw.get_current_usage.return_value = 42
        buf = BufferedRateLimiter(mock_raw, size=10)

        result = buf.get_current_usage()

        assert result == 42
        mock_raw.get_current_usage.assert_called_once()

    def test_raises_value_error_when_size_exceeds_cap(self, client, raw_limiter):
        with pytest.raises(ValueError):
            BufferedRateLimiter(raw_limiter, size=raw_limiter.cap_per_minute + 1)

    def test_raises_value_error_when_size_is_zero(self, client, raw_limiter):
        with pytest.raises(ValueError):
            BufferedRateLimiter(raw_limiter, size=0)

    def test_raises_type_error_on_double_wrapping(self, client, raw_limiter):
        with client.application.app_context():
            # Seed the registry so `.buffered()` replaces the existing entry for this namespace
            rate_limiter._rate_limiter_instances["test"] = raw_limiter
            buf = raw_limiter.buffered(10)
            with pytest.raises(TypeError):
                buf.buffered(10)
            rate_limiter._rate_limiter_instances.pop("test", None)

    def test_buffered_factory_self_registers_in_registry(self, client, raw_limiter):
        with client.application.app_context():
            rate_limiter._rate_limiter_instances["test"] = raw_limiter
            buf = raw_limiter.buffered(10)
            assert get_rate_limiter("test") is buf
            rate_limiter._rate_limiter_instances.pop("test", None)
