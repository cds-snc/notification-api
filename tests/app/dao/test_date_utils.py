from datetime import date, datetime

import pytest
import pytz

from app.dao.date_util import (
    get_april_fools,
    get_financial_year,
    get_financial_year_for_datetime,
    get_midnight,
    get_month_start_and_end_date_in_utc,
)


def test_get_financial_year():
    start, end = get_financial_year(2000)
    assert str(start) == "2000-04-01 05:00:00"
    assert str(end) == "2001-04-01 04:59:59.999999"


def test_get_april_fools():
    april_fools = get_april_fools(2016)
    assert str(april_fools) == "2016-04-01 04:00:00"
    assert april_fools.tzinfo is None


@pytest.mark.parametrize(
    "month, year, expected_start, expected_end",
    [
        (
            7,
            2017,
            datetime(2017, 7, 1, 4, 00, 00),
            datetime(2017, 8, 1, 3, 59, 59, 99999),
        ),
        (
            2,
            2016,
            datetime(2016, 2, 1, 5, 00, 00),
            datetime(2016, 3, 1, 4, 59, 59, 99999),
        ),
        (
            2,
            2017,
            datetime(2017, 2, 1, 5, 00, 00),
            datetime(2017, 3, 1, 4, 59, 59, 99999),
        ),
        (
            9,
            2018,
            datetime(2018, 9, 1, 4, 00, 00),
            datetime(2018, 10, 1, 3, 59, 59, 99999),
        ),
        (
            12,
            2019,
            datetime(2019, 12, 1, 5, 00, 00),
            datetime(2020, 1, 1, 4, 59, 59, 99999),
        ),
    ],
)
def test_get_month_start_and_end_date_in_utc(month, year, expected_start, expected_end):
    month_year = datetime(year, month, 10, 13, 30, 00)
    start, end = get_month_start_and_end_date_in_utc(month_year)
    assert start == expected_start
    assert end == expected_end


@pytest.mark.parametrize(
    "dt, fy",
    [
        (datetime(2018, 4, 1, 5, 0, 0), 2018),
        (datetime(2019, 3, 31, 22, 59, 59), 2018),
        (datetime(2019, 4, 1, 5, 0, 0), 2019),
        (date(2019, 3, 31), 2018),
        (date(2019, 4, 2), 2019),
    ],
)
def test_get_financial_year_for_datetime(dt, fy):
    assert get_financial_year_for_datetime(dt) == fy


class TestMidnightDateTime:

    eastern = pytz.timezone("US/Eastern")
    utc = pytz.utc

    @pytest.mark.parametrize(
        "current_time, expected_midnight",
        [
            (
                datetime(2022, 7, 1, 0, 00, 00, tzinfo=utc),
                datetime(2022, 7, 1, 0, 00, 00, tzinfo=utc),
            ),
            (
                datetime(2022, 7, 1, 4, 00, 00, tzinfo=utc),
                datetime(2022, 7, 1, 0, 00, 00, tzinfo=utc),
            ),
            (
                datetime(2022, 7, 1, 23, 59, 59, tzinfo=utc),
                datetime(2022, 7, 1, 0, 00, 00, tzinfo=utc),
            ),
            (
                datetime(2022, 7, 1, 4, 00, 00, tzinfo=utc),
                datetime(2022, 7, 1, 0, 00, 00, tzinfo=utc),
            ),
            (
                datetime(2022, 7, 1, 5, 00, 00, tzinfo=utc),
                datetime(2022, 7, 1, 0, 00, 00, tzinfo=utc),
            ),
            (
                datetime(2022, 7, 1, 20, 00, 00, tzinfo=utc),
                datetime(2022, 7, 1, 0, 00, 00, tzinfo=utc),
            ),
            (
                datetime(2022, 7, 1, 18, 00, 00, tzinfo=utc),
                datetime(2022, 7, 1, 0, 00, 00, tzinfo=utc),
            ),
            (
                datetime(2022, 7, 1, 18, 00, 00, tzinfo=eastern),
                datetime(2022, 7, 1, 0, 00, 00, tzinfo=eastern),
            ),
            (
                datetime(2022, 7, 1, 20, 00, 00, tzinfo=eastern),
                datetime(2022, 7, 1, 0, 00, 00, tzinfo=eastern),
            ),
        ],
    )
    def test_get_midnight(self, current_time, expected_midnight):
        actual = get_midnight(current_time)
        assert expected_midnight == actual
