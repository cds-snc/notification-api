import pytest
from notifications_utils.clients.redis import email_daily_count_cache_key

from app.email_limit_utils import (
    decrement_todays_email_count,
    fetch_todays_email_count,
    increment_todays_email_count,
)
from tests.conftest import set_config


class TestEmailLimits:
    @pytest.mark.parametrize("redis_value, db_value, expected_result", [(None, 5, 5), ("3", 5, 3)])
    def test_fetch_todays_requested_email_count(self, client, mocker, sample_service, redis_value, db_value, expected_result):
        cache_key = email_daily_count_cache_key(sample_service.id)
        mocker.patch("app.redis_store.get", lambda x: redis_value if x == cache_key else None)
        mocked_set = mocker.patch("app.redis_store.set")
        mocker.patch("app.email_limit_utils.fetch_todays_total_email_count", return_value=db_value)
        # mocker.patch("app.dao.users_dao.user_can_be_archived", return_value=False)

        with set_config(client.application, "REDIS_ENABLED", True):
            actual_result = fetch_todays_email_count(sample_service.id)

            assert actual_result == expected_result
            if redis_value is None:
                mocked_set.assert_called_once_with(
                    cache_key,
                    db_value,
                    ex=7200,
                )
            else:
                mocked_set.assert_not_called()

    @pytest.mark.parametrize("redis_value, db_value, increment_by", [(None, 5, 5), ("3", 5, 3)])
    def test_increment_todays_requested_email_count(self, client, mocker, sample_service, redis_value, db_value, increment_by):
        cache_key = email_daily_count_cache_key(sample_service.id)
        mocker.patch("app.redis_store.get", lambda x: redis_value if x == cache_key else None)
        mocked_incrby = mocker.patch("app.redis_store.incrby")
        mocker.patch("app.email_limit_utils.fetch_todays_email_count", return_value=db_value)

        with set_config(client.application, "REDIS_ENABLED", True):
            increment_todays_email_count(sample_service.id, increment_by)
            mocked_incrby.assert_called_once_with(cache_key, increment_by)

    @pytest.mark.parametrize("decrby_result, expect_reset_to_zero", [(3, False), (0, False), (-2, True)])
    def test_decrement_todays_email_count_never_goes_below_zero(
        self, client, mocker, sample_service, decrby_result, expect_reset_to_zero
    ):
        cache_key = email_daily_count_cache_key(sample_service.id)
        mocker.patch("app.redis_store.get", return_value=b"5")
        mocked_decrby = mocker.patch("app.redis_store.decrby", return_value=decrby_result)
        mocked_set = mocker.patch("app.redis_store.set")

        with set_config(client.application, "REDIS_ENABLED", True):
            decrement_todays_email_count(sample_service.id, 5)

        mocked_decrby.assert_called_once_with(cache_key, 5)
        if expect_reset_to_zero:
            mocked_set.assert_called_once_with(cache_key, 0, ex=7200)
        else:
            mocked_set.assert_not_called()

    def test_decrement_todays_email_count_does_nothing_when_not_in_redis(self, client, mocker, sample_service):
        mocker.patch("app.redis_store.get", return_value=None)
        mocked_fetch = mocker.patch("app.email_limit_utils.fetch_todays_total_email_count")
        mocked_decrby = mocker.patch("app.redis_store.decrby")

        with set_config(client.application, "REDIS_ENABLED", True):
            decrement_todays_email_count(sample_service.id, 5)

        mocked_fetch.assert_not_called()
        mocked_decrby.assert_not_called()
