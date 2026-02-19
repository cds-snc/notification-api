import pytest
from notifications_utils.clients.redis import billable_units_sms_daily_count_cache_key, sms_daily_count_cache_key

from app.sms_fragment_utils import (
    fetch_todays_requested_sms_billable_units_count,
    fetch_todays_requested_sms_count,
    increment_todays_requested_sms_billable_units_count,
    increment_todays_requested_sms_count,
)
from tests.conftest import set_config


@pytest.mark.parametrize("redis_value,db_value,expected_result", [(None, 5, 5), ("3", 5, 3)])
def test_fetch_todays_requested_sms_count(client, mocker, sample_service, redis_value, db_value, expected_result):
    cache_key = sms_daily_count_cache_key(sample_service.id)
    mocker.patch("app.redis_store.get", lambda x: redis_value if x == cache_key else None)
    mocked_set = mocker.patch("app.redis_store.set")
    mocker.patch("app.sms_fragment_utils.fetch_todays_total_sms_count", return_value=db_value)
    mocker.patch("app.dao.users_dao.user_can_be_archived", return_value=False)

    with set_config(client.application, "REDIS_ENABLED", True):
        actual_result = fetch_todays_requested_sms_count(sample_service.id)

        assert actual_result == expected_result
        if redis_value is None:
            mocked_set.assert_called_once_with(
                cache_key,
                db_value,
                ex=7200,
            )
        else:
            mocked_set.assert_not_called()


@pytest.mark.parametrize("redis_value,db_value,increment_by", [(None, 5, 5), ("3", 5, 3)])
def test_increment_todays_requested_sms_count(mocker, client, sample_service, redis_value, db_value, increment_by):
    cache_key = sms_daily_count_cache_key(sample_service.id)
    mocker.patch("app.redis_store.get", lambda x: redis_value if x == cache_key else None)
    mocked_incrby = mocker.patch("app.redis_store.incrby")
    mocker.patch("app.sms_fragment_utils.fetch_todays_requested_sms_count", return_value=db_value)

    with set_config(client.application, "REDIS_ENABLED", True):
        increment_todays_requested_sms_count(sample_service.id, increment_by)
        mocked_incrby.assert_called_once_with(cache_key, increment_by)


# TODO: Remove feature flag checks after FF_USE_BILLABLE_UNITS go live
class TestBillableUnitsInSmsFragmentUtils:
    """Tests for billable_units functionality in sms_fragment_utils"""

    @pytest.mark.parametrize("redis_value,db_value,expected_result", [(None, 10, 10), ("15", 10, 15)])
    def test_fetch_todays_requested_sms_billable_units_count(
        self, client, mocker, sample_service, redis_value, db_value, expected_result
    ):
        """Test fetch_todays_requested_sms_billable_units_count returns correct value from Redis or DB"""

        cache_key = billable_units_sms_daily_count_cache_key(sample_service.id)
        mocker.patch("app.redis_store.get", lambda x: redis_value if x == cache_key else None)
        mocked_set = mocker.patch("app.redis_store.set")
        mocker.patch("app.sms_fragment_utils.fetch_todays_total_sms_billable_units", return_value=db_value)

        with set_config(client.application, "REDIS_ENABLED", True):
            actual_result = fetch_todays_requested_sms_billable_units_count(sample_service.id)

            assert actual_result == expected_result
            if redis_value is None:
                # Should cache the DB value
                mocked_set.assert_called_once_with(cache_key, db_value, ex=7200)
            else:
                # Should use cached value
                mocked_set.assert_not_called()

    @pytest.mark.skip(reason="Temporarily disabled")
    def test_fetch_todays_requested_sms_billable_units_count_falls_back_to_db_when_redis_disabled(
        self, client, mocker, sample_service
    ):
        """Test that function falls back to DB when Redis is disabled"""

        mock_fetch_db = mocker.patch("app.sms_fragment_utils.fetch_todays_total_sms_billable_units", return_value=25)

        with set_config(client.application, "REDIS_ENABLED", False):
            result = fetch_todays_requested_sms_billable_units_count(sample_service.id)

            assert result == 25
            mock_fetch_db.assert_called_once_with(sample_service.id)

    @pytest.mark.parametrize("redis_value,db_value,increment_by", [(None, 10, 5), ("20", 10, 3)])
    def test_increment_todays_requested_sms_billable_units_count(
        self, mocker, client, sample_service, redis_value, db_value, increment_by
    ):
        """Test increment_todays_requested_sms_billable_units_count increments Redis counter"""

        cache_key = billable_units_sms_daily_count_cache_key(sample_service.id)
        mocker.patch("app.redis_store.get", lambda x: redis_value if x == cache_key else None)
        mocked_incrby = mocker.patch("app.redis_store.incrby")
        mocker.patch("app.sms_fragment_utils.fetch_todays_requested_sms_billable_units_count", return_value=db_value)

        with set_config(client.application, "REDIS_ENABLED", True):
            increment_todays_requested_sms_billable_units_count(sample_service.id, increment_by)

            # Should increment by the specified amount
            mocked_incrby.assert_called_once_with(cache_key, increment_by)

    @pytest.mark.skip(reason="Temporarily disabled")
    def test_increment_todays_requested_sms_billable_units_count_does_nothing_when_redis_disabled(
        self, mocker, client, sample_service
    ):
        """Test that increment does nothing when Redis is disabled"""

        mock_incrby = mocker.patch("app.redis_store.incrby")

        with set_config(client.application, "REDIS_ENABLED", False):
            increment_todays_requested_sms_billable_units_count(sample_service.id, 5)

            # Should not attempt to increment when Redis is disabled
            mock_incrby.assert_not_called()
