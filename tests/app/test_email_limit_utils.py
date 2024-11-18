import pytest
from notifications_utils.clients.redis import email_daily_count_cache_key

from app.email_limit_utils import fetch_todays_email_count, increment_todays_email_count
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
    def test_increment_todays_requested_email_count(self, mocker, sample_service, redis_value, db_value, increment_by):
        cache_key = email_daily_count_cache_key(sample_service.id)
        mocker.patch("app.redis_store.get", lambda x: redis_value if x == cache_key else None)
        mocked_incrby = mocker.patch("app.redis_store.incrby")
        mocker.patch("app.email_limit_utils.fetch_todays_email_count", return_value=db_value)

        increment_todays_email_count(sample_service.id, increment_by)

        mocked_incrby.assert_called_once_with(cache_key, increment_by)