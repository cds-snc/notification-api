from datetime import date, datetime, timedelta, timezone

import pytest
from flask import Flask
from freezegun import freeze_time

from app.config import QueueNames
from app.models import EMAIL_TYPE, SMS_TYPE
from app.utils import (
    get_delivery_queue_for_template,
    get_document_url,
    get_fiscal_dates,
    get_fiscal_year,
    get_limit_reset_time_et,
    get_local_timezone_midnight,
    get_local_timezone_midnight_in_utc,
    get_logo_url,
    get_midnight_for_day_before,
    midnight_n_days_ago,
    rate_limit_db_calls,
    store_dev_verification_data,
    update_dct_to_str,
)
from tests.app.db import create_template


# Naive date times are ambiguous and are treated different on Mac OS vs flavours of *nix
# Mac OS treats naive datetime as local time to the host machine while *nix treats it as GMT time
# We can see this when applying timezones "US/Eastern" of naive times to a datetime on the different platforms
# they will result in different values. Within this test we normalize the naive datetime to UTC to properly
# pass the test on both Mac and *nix
@pytest.mark.parametrize(
    "date_val, expected_date",
    [
        (
            datetime(2016, 1, 15, 0, 30, tzinfo=timezone.utc),
            datetime(2016, 1, 14, 5, 0),
        ),
        (datetime(2016, 6, 15, 0, 0, tzinfo=timezone.utc), datetime(2016, 6, 14, 4, 0)),
        (datetime(2016, 9, 16, 4, 0, tzinfo=timezone.utc), datetime(2016, 9, 16, 4, 0)),
    ],
)
def test_get_local_timezone_midnight_returns_expected_date_for_datetime(date_val: datetime, expected_date: datetime):
    assert get_local_timezone_midnight(date_val) == expected_date


@pytest.mark.parametrize(
    "date_val, expected_date",
    [
        (date(2016, 1, 15), datetime(2016, 1, 14, 5, 0)),
        (date(2016, 6, 15), datetime(2016, 6, 14, 4, 0)),
    ],
)
def test_get_local_timezone_midnight_returns_expected_date_for_date(date_val: date, expected_date: datetime):
    # based upon the comment above we localize date to a datetime with a time of midnight with tz of utc
    dt = datetime.combine(date_val, datetime.min.time(), tzinfo=timezone.utc)
    assert get_local_timezone_midnight(dt) == expected_date


@pytest.mark.parametrize(
    "date, expected_date",
    [
        (datetime(2016, 1, 15, 0, 30), datetime(2016, 1, 15, 5, 0)),
        (datetime(2016, 6, 15, 0, 0), datetime(2016, 6, 15, 4, 0)),
        (datetime(2016, 9, 15, 11, 59), datetime(2016, 9, 15, 4, 0)),
        # works for both dates and datetimes
        (date(2016, 1, 15), datetime(2016, 1, 15, 5, 0)),
        (date(2016, 6, 15), datetime(2016, 6, 15, 4, 0)),
    ],
)
def test_get_local_timezone_midnight_in_utc_returns_expected_date(date, expected_date):
    assert get_local_timezone_midnight_in_utc(date) == expected_date


@pytest.mark.parametrize(
    "date, expected_date",
    [
        (datetime(2016, 1, 15, 0, 30), datetime(2016, 1, 14, 5, 0)),
        (datetime(2016, 7, 15, 0, 0), datetime(2016, 7, 14, 4, 0)),
        (datetime(2016, 8, 23, 11, 59), datetime(2016, 8, 22, 4, 0)),
    ],
)
def test_get_midnight_for_day_before_returns_expected_date(date, expected_date):
    assert get_midnight_for_day_before(date) == expected_date


@pytest.mark.parametrize(
    "current_time, arg, expected_datetime",
    [
        # winter
        ("2018-01-10 23:59", 1, datetime(2018, 1, 9, 5, 0)),
        ("2018-01-11 00:00", 1, datetime(2018, 1, 10, 5, 0)),
        # bst switchover at 1am 25th
        ("2018-03-25 10:00", 1, datetime(2018, 3, 24, 4, 0)),
        ("2018-03-26 10:00", 1, datetime(2018, 3, 25, 4, 0)),
        ("2018-03-27 10:00", 1, datetime(2018, 3, 26, 4, 0)),
        # summer
        ("2018-06-05 10:00", 1, datetime(2018, 6, 4, 4, 0)),
        # zero days ago
        ("2018-01-11 00:00", 0, datetime(2018, 1, 11, 5, 0)),
        ("2018-06-05 10:00", 0, datetime(2018, 6, 5, 4, 0)),
    ],
)
def test_midnight_n_days_ago(current_time, arg, expected_datetime):
    with freeze_time(current_time):
        assert midnight_n_days_ago(arg) == expected_datetime


def test_update_dct_to_str():
    test_dict = {
        "email_address": "test@test.com",
        "auth_type": "sms",
        "dummy_key": "nope",
    }
    result = update_dct_to_str(test_dict, "EN")
    result = " ".join(result.split())
    expected = ["- email address", "- auth type", "- dummy key"]
    expected = " ".join(expected)

    assert result == expected

    result = update_dct_to_str(test_dict, "FR")
    result = " ".join(result.split())
    expected = ["- adresse courriel", "- méthode d'authentification", "- dummy key"]
    expected = " ".join(expected)

    assert result == expected


def test_get_logo_url(notify_api):
    with notify_api.app_context():
        assert get_logo_url("foo.png") == "https://assets.notification.canada.ca/foo.png"


def test_get_document_url(notify_api: Flask):
    with notify_api.app_context():
        assert get_document_url("en", "test.html") == "https://documentation.notification.canada.ca/en/test.html"
        assert get_document_url("None", "None") == "https://documentation.notification.canada.ca/None/None"


def test_get_limit_reset_time_et():
    # the daily limit resets at 8PM or 7PM depending on whether it's daylight savings time or not
    with freeze_time("2023-08-10 00:00"):
        assert get_limit_reset_time_et() == {"12hr": "8PM", "24hr": "20"}
    with freeze_time("2023-01-10 00:00"):
        assert get_limit_reset_time_et() == {"12hr": "7PM", "24hr": "19"}


@pytest.mark.parametrize(
    "template_type, process_type, expected_queue",
    [
        (SMS_TYPE, "normal", QueueNames.SEND_SMS_MEDIUM),
        (SMS_TYPE, "priority", QueueNames.SEND_SMS_HIGH),
        (SMS_TYPE, "bulk", QueueNames.SEND_SMS_LOW),
        (EMAIL_TYPE, "normal", QueueNames.SEND_EMAIL_MEDIUM),
        (EMAIL_TYPE, "priority", QueueNames.SEND_EMAIL_HIGH),
        (EMAIL_TYPE, "bulk", QueueNames.SEND_EMAIL_LOW),
    ],
)
def test_get_delivery_queue_for_template(sample_service, template_type, process_type, expected_queue):
    template = create_template(sample_service, process_type=process_type, template_type=template_type)
    assert get_delivery_queue_for_template(template) == expected_queue


@pytest.mark.parametrize(
    "current_date, expected_fiscal_year",
    [
        (datetime(2023, 3, 31), 2022),
        (datetime(2023, 4, 1), 2023),
        (datetime(2023, 12, 31), 2023),
        (None, datetime.today().year if datetime.today().month >= 4 else datetime.today().year - 1),
    ],
)
def test_get_fiscal_year(current_date, expected_fiscal_year):
    assert get_fiscal_year(current_date) == expected_fiscal_year


@freeze_time("2024-11-28")
@pytest.mark.parametrize(
    "current_date, year, expected_start, expected_end",
    [
        (datetime(2023, 3, 31), None, datetime(2022, 4, 1), datetime(2023, 3, 31)),
        (datetime(2023, 4, 1), None, datetime(2023, 4, 1), datetime(2024, 3, 31)),
        (None, 2023, datetime(2023, 4, 1), datetime(2024, 3, 31)),
        (None, None, datetime(2024, 4, 1), datetime(2025, 3, 31)),
    ],
)
def test_get_fiscal_dates(current_date, year, expected_start, expected_end):
    assert get_fiscal_dates(current_date, year) == (expected_start, expected_end)


def test_get_fiscal_dates_raises_value_error():
    with pytest.raises(ValueError):
        get_fiscal_dates(current_date=datetime(2023, 4, 1), year=2023)


def test_rate_limit_db_calls_no_redis(notify_api, mocker):
    mock_redis = mocker.patch("app.redis_store.get")
    mock_redis_set = mocker.patch("app.redis_store.set")

    # Create test function with rate limiting
    @rate_limit_db_calls("test_prefix")
    def limited_function(key_id):
        return "called"

    with notify_api.test_request_context():
        # Disable redis
        notify_api.config["REDIS_ENABLED"] = False

        # Should call through without checking redis
        result = limited_function("123")
        assert result == "called"
        mock_redis.assert_not_called()
        mock_redis_set.assert_not_called()


def test_rate_limit_db_calls_first_call(notify_api, mocker):
    mock_redis = mocker.patch("app.redis_store.get", return_value=None)
    mock_redis_set = mocker.patch("app.redis_store.set")

    @rate_limit_db_calls("test_prefix", period_seconds=30)
    def limited_function(key_id):
        return "called"

    with notify_api.test_request_context():
        notify_api.config["REDIS_ENABLED"] = True

        # First call should succeed and set redis key
        result = limited_function("123")
        assert result == "called"
        mock_redis.assert_called_once_with("test_prefix:123")
        mock_redis_set.assert_called_once_with("test_prefix:123", "1", ex=30)


def test_rate_limit_db_calls_blocked(notify_api, mocker):
    mock_redis = mocker.patch("app.redis_store.get", return_value="1")
    mock_redis_set = mocker.patch("app.redis_store.set")

    @rate_limit_db_calls("test_prefix")
    def limited_function(key_id):
        return "called"

    with notify_api.test_request_context():
        notify_api.config["REDIS_ENABLED"] = True

        # Call should be blocked by existing redis key
        result = limited_function("123")
        assert result is None
        mock_redis.assert_called_once_with("test_prefix:123")
        mock_redis_set.assert_not_called()


class TestStoreDevVerificationData:
    """Tests for store_dev_verification_data function"""

    @pytest.mark.parametrize(
        "environment,host,should_store,test_description",
        [
            # Environment tests
            ("development", "localhost:3000", True, "stores data in development mode with valid host"),
            ("production", "localhost:3000", False, "does not store data in production mode"),
            ("staging", "localhost:3000", False, "does not store data in staging mode"),
            # Host filtering tests
            ("development", "staging.notification.canada.ca", False, "does not store when host contains notification.canada.ca"),
            (
                "development",
                "api.notification.canada.ca",
                False,
                "does not store when host contains notification.canada.ca subdomain",
            ),
            ("development", "notification.canada.ca", False, "does not store when host is exactly notification.canada.ca"),
            # Combined conditions
            (
                "production",
                "api.notification.canada.ca",
                False,
                "does not store when both environment is not dev AND host contains notification.canada.ca",
            ),
            # Valid development hosts
            ("development", "localhost", True, "stores data with localhost"),
            ("development", "localhost:5000", True, "stores data with localhost:5000"),
            ("development", "127.0.0.1", True, "stores data with 127.0.0.1"),
            ("development", "127.0.0.1:8080", True, "stores data with 127.0.0.1:8080"),
            ("development", "dev.example.com", True, "stores data with dev.example.com"),
            ("development", "test-environment.com", True, "stores data with test-environment.com"),
        ],
    )
    def test_store_dev_verification_data_conditions(self, notify_api, mocker, environment, host, should_store, test_description):
        """Test various environment and host conditions for storing verification data"""
        with notify_api.test_request_context():
            # Arrange
            mock_current_app = mocker.patch("app.utils.current_app")
            mock_request = mocker.patch("app.utils.request")
            mock_redis_store = mocker.patch("app.utils.redis_store")

            mock_current_app.config = {"NOTIFY_ENVIRONMENT": environment}
            mock_request.host = host
            user_id = "test-user-123"
            data = "test-verification-code"

            # Act
            store_dev_verification_data("verify_code", user_id, data)

            # Assert
            if should_store:
                mock_redis_store.set.assert_called_once_with(
                    "verify_code_test-user-123", "test-verification-code", ex=timedelta(minutes=1)
                )
            else:
                mock_redis_store.set.assert_not_called()

    @pytest.mark.parametrize(
        "key_prefix,user_id,data,expected_key",
        [
            ("verify_code", "test-user-123", "123456", "verify_code_test-user-123"),
            ("verify_url", "test-user-123", "https://example.com/verify", "verify_url_test-user-123"),
            ("verify_code", "550e8400-e29b-41d4-a716-446655440000", "789012", "verify_code_550e8400-e29b-41d4-a716-446655440000"),
            (
                "verify_url",
                "550e8400-e29b-41d4-a716-446655440000",
                "https://verify.test.com",
                "verify_url_550e8400-e29b-41d4-a716-446655440000",
            ),
        ],
    )
    def test_store_dev_verification_data_key_formats(self, notify_api, mocker, key_prefix, user_id, data, expected_key):
        """Test different key prefixes and user ID formats"""
        with notify_api.test_request_context():
            # Arrange
            mock_current_app = mocker.patch("app.utils.current_app")
            mock_request = mocker.patch("app.utils.request")
            mock_redis_store = mocker.patch("app.utils.redis_store")

            mock_current_app.config = {"NOTIFY_ENVIRONMENT": "development"}
            mock_request.host = "localhost:3000"

            # Act
            store_dev_verification_data(key_prefix, user_id, data)

            # Assert
            mock_redis_store.set.assert_called_once_with(expected_key, data, ex=timedelta(minutes=1))
