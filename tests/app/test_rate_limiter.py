from unittest.mock import patch

import fakeredis
import pytest

from app.rate_limiter import (
    InMemoryRateLimiter,
    RedisSlidingWindowLogRateLimiter,
    RedisTokenBucketRateLimiter,
    initialize_rate_limiter,
)


class TestInMemoryRateLimiter:
    @pytest.fixture
    def limiter(self):
        return InMemoryRateLimiter(cap_per_minute=1000)

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


class TestRedisRateLimiter:
    @pytest.fixture
    def limiter(self):
        redis_client = fakeredis.FakeRedis()
        return RedisSlidingWindowLogRateLimiter(cap_per_minute=1000, redis_client=redis_client)

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
        return RedisTokenBucketRateLimiter(cap_per_minute=1000, redis_client=redis_client)

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

    def test_get_current_usage_returns_consumed_parts(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(150)
                limiter.acquire_lease(250)
                # freeze time so no refill occurs during get_current_usage
                assert limiter.get_current_usage() == 400

    def test_get_current_usage_zero_when_bucket_empty(self, client, limiter):
        with client.application.app_context():
            assert limiter.get_current_usage() == 0

    def test_retry_delay_is_precise(self, client, limiter):
        # Token bucket wait time = ceil(deficit / refill_rate)
        # refill_rate = 1000 / 60 ≈ 16.67 parts/sec
        # After consuming 1000/1000, requesting 100 more:
        # deficit = 100, wait = ceil(100 / 16.67) = ceil(5.999) = 6
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(1000)
                allow_send, wait_seconds = limiter.acquire_lease(100)
                assert allow_send is False
                import math

                expected = math.ceil(100 / (1000 / 60))
                assert wait_seconds == expected

    def test_capacity_refills_over_time(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(1000)

                # Advance 30 seconds — should have refilled 1000/60 * 30 = 500 tokens
                mock_time.return_value = 130.0
                allow_send, _ = limiter.acquire_lease(500)
                assert allow_send is True

    def test_bucket_does_not_exceed_cap_after_idle(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(500)

                # Advance 120 seconds — bucket should be capped at 1000, not 500 + 1000/60*120
                mock_time.return_value = 220.0
                allow_send, _ = limiter.acquire_lease(1000)
                assert allow_send is True

    def test_burst_after_idle_allows_full_cap(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                # Use up full capacity
                limiter.acquire_lease(1000)

                # Advance 60 seconds — bucket fully refilled
                mock_time.return_value = 160.0
                allow_send, _ = limiter.acquire_lease(1000)
                assert allow_send is True

    def test_reset_clears_bucket(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(1000)
                allow_send, _ = limiter.acquire_lease(100)
                assert allow_send is False

                limiter.reset_limiter()
                # After reset, bucket is gone; next call initialises fresh full bucket
                allow_send, _ = limiter.acquire_lease(1000)
                assert allow_send is True

    def test_multiple_sequential_acquires_deplete_tokens(self, client, limiter):
        with client.application.app_context():
            with patch("app.rate_limiter.time") as mock_time:
                mock_time.return_value = 100.0
                limiter.acquire_lease(400)
                limiter.acquire_lease(400)
                limiter.acquire_lease(200)
                # Bucket now at 0
                allow_send, _ = limiter.acquire_lease(1)
                assert allow_send is False


class TestInitializeRateLimiter:
    def teardown_method(self):
        # Reset global singleton between tests
        import app.rate_limiter as rl

        rl._rate_limiter_instance = None

    def test_explicit_class_arg_takes_precedence(self, client):
        with client.application.app_context():
            redis_client = fakeredis.FakeRedis()
            # Pass class directly; config should be ignored
            instance = initialize_rate_limiter(1000, RedisTokenBucketRateLimiter)
            assert isinstance(instance, RedisTokenBucketRateLimiter)

    def test_explicit_in_memory_class_arg(self, client):
        with client.application.app_context():
            instance = initialize_rate_limiter(1000, InMemoryRateLimiter)
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
                        instance = initialize_rate_limiter(1000)
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
                    instance = initialize_rate_limiter(1000)
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
                    instance = initialize_rate_limiter(1000)
                    assert isinstance(instance, InMemoryRateLimiter)

    def test_default_no_args_uses_in_memory(self, client):
        with client.application.app_context():
            with patch("app.config.Config.SMS_RATE_LIMITER_BACKEND", "InMemoryRateLimiter", create=True):
                instance = initialize_rate_limiter(1000)
                assert isinstance(instance, InMemoryRateLimiter)
