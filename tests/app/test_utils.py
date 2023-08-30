from datetime import date, datetime, timezone

import pytest
from flask import Flask
from freezegun import freeze_time

from app.config import QueueNames
from app.models import EMAIL_TYPE, SMS_TYPE
from app.utils import (
    get_delivery_queue_for_template,
    get_document_url,
    get_limit_reset_time_et,
    get_local_timezone_midnight,
    get_local_timezone_midnight_in_utc,
    get_logo_url,
    get_midnight_for_day_before,
    midnight_n_days_ago,
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
        (EMAIL_TYPE, "normal", QueueNames.SEND_EMAIL),
        (EMAIL_TYPE, "priority", QueueNames.PRIORITY),
        (EMAIL_TYPE, "bulk", QueueNames.BULK),
    ],
)
def test_get_delivery_queue_for_template(sample_service, template_type, process_type, expected_queue):
    template = create_template(sample_service, process_type=process_type, template_type=template_type)
    assert get_delivery_queue_for_template(template) == expected_queue
