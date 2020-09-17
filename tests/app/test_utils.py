from datetime import datetime, date

import pytest
from freezegun import freeze_time

from app.utils import (
    get_local_timezone_midnight,
    get_local_timezone_midnight_in_utc,
    get_midnight_for_day_before,
    midnight_n_days_ago,
    update_dct_to_str
)


@pytest.mark.parametrize('date, expected_date', [
    (datetime(2016, 1, 15, 0, 30), datetime(2016, 1, 14, 5, 0)),
    (datetime(2016, 6, 15, 0, 0), datetime(2016, 6, 14, 4, 0)),
    (datetime(2016, 9, 16, 4, 0), datetime(2016, 9, 16, 4, 0)),
    # works for both dates and datetimes
    (date(2016, 1, 15), datetime(2016, 1, 14, 5, 0)),
    (date(2016, 6, 15), datetime(2016, 6, 14, 4, 0)),
])
def test_get_local_timezone_midnight_returns_expected_date(date, expected_date):
    assert get_local_timezone_midnight(date) == expected_date


@pytest.mark.parametrize('date, expected_date', [
    (datetime(2016, 1, 15, 0, 30), datetime(2016, 1, 15, 5, 0)),
    (datetime(2016, 6, 15, 0, 0), datetime(2016, 6, 15, 4, 0)),
    (datetime(2016, 9, 15, 11, 59), datetime(2016, 9, 15, 4, 0)),
    # works for both dates and datetimes
    (date(2016, 1, 15), datetime(2016, 1, 15, 5, 0)),
    (date(2016, 6, 15), datetime(2016, 6, 15, 4, 0)),
])
def test_get_local_timezone_midnight_in_utc_returns_expected_date(date, expected_date):
    assert get_local_timezone_midnight_in_utc(date) == expected_date


@pytest.mark.parametrize('date, expected_date', [
    (datetime(2016, 1, 15, 0, 30), datetime(2016, 1, 14, 5, 0)),
    (datetime(2016, 7, 15, 0, 0), datetime(2016, 7, 14, 4, 0)),
    (datetime(2016, 8, 23, 11, 59), datetime(2016, 8, 22, 4, 0)),
])
def test_get_midnight_for_day_before_returns_expected_date(date, expected_date):
    assert get_midnight_for_day_before(date) == expected_date


@pytest.mark.parametrize('current_time, arg, expected_datetime', [
    # winter
    ('2018-01-10 23:59', 1, datetime(2018, 1, 9, 5, 0)),
    ('2018-01-11 00:00', 1, datetime(2018, 1, 10, 5, 0)),

    # bst switchover at 1am 25th
    ('2018-03-25 10:00', 1, datetime(2018, 3, 24, 4, 0)),
    ('2018-03-26 10:00', 1, datetime(2018, 3, 25, 4, 0)),
    ('2018-03-27 10:00', 1, datetime(2018, 3, 26, 4, 0)),

    # summer
    ('2018-06-05 10:00', 1, datetime(2018, 6, 4, 4, 0)),

    # zero days ago
    ('2018-01-11 00:00', 0, datetime(2018, 1, 11, 5, 0)),
    ('2018-06-05 10:00', 0, datetime(2018, 6, 5, 4, 0)),
])
def test_midnight_n_days_ago(current_time, arg, expected_datetime):
    with freeze_time(current_time):
        assert midnight_n_days_ago(arg) == expected_datetime


def test_update_dct_to_str():
    test_dict = {
        "email_address": "test@test.com",
        "auth_type": "sms",
        "dummy_key": "nope",
    }
    result = update_dct_to_str(test_dict, 'EN')
    result = ' '.join(result.split())
    expected = ["- email address", "- auth type", "- dummy key"]
    expected = ' '.join(expected)

    assert result == expected

    result = update_dct_to_str(test_dict, 'FR')
    result = ' '.join(result.split())
    expected = ["- adresse courriel", "- méthode d'authentification", "- dummy key"]
    expected = ' '.join(expected)

    assert result == expected
