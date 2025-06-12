from datetime import datetime, date
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from app.utils import (
    get_local_timezone_midnight,
    get_local_timezone_midnight_in_utc,
    get_midnight_for_day_before,
    midnight_n_days_ago,
    statsd_http,
)


@pytest.mark.skip(reason='failing on a machine with US/Eastern timezone')
@pytest.mark.parametrize(
    'date, expected_date',
    [
        (datetime(2016, 1, 15, 0, 30), datetime(2016, 1, 14, 5, 0)),
        (datetime(2016, 6, 15, 0, 0), datetime(2016, 6, 14, 4, 0)),
        (datetime(2016, 9, 16, 4, 0), datetime(2016, 9, 16, 4, 0)),
        # works for both dates and datetimes
        (date(2016, 1, 15), datetime(2016, 1, 14, 5, 0)),
        (date(2016, 6, 15), datetime(2016, 6, 14, 4, 0)),
    ],
)
def test_get_local_timezone_midnight_returns_expected_date(date, expected_date):
    assert get_local_timezone_midnight(date) == expected_date


@pytest.mark.parametrize(
    'date, expected_date',
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
    'date, expected_date',
    [
        (datetime(2016, 1, 15, 0, 30), datetime(2016, 1, 14, 5, 0)),
        (datetime(2016, 7, 15, 0, 0), datetime(2016, 7, 14, 4, 0)),
        (datetime(2016, 8, 23, 11, 59), datetime(2016, 8, 22, 4, 0)),
    ],
)
def test_get_midnight_for_day_before_returns_expected_date(date, expected_date):
    assert get_midnight_for_day_before(date) == expected_date


@pytest.mark.parametrize(
    'current_time, arg, expected_datetime',
    [
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
    ],
)
def test_midnight_n_days_ago(current_time, arg, expected_datetime):
    with freeze_time(current_time):
        assert midnight_n_days_ago(arg) == expected_datetime


def test_statsd_http_success_logs_stats(mocker):
    """Ensure statsd_http context manager logs success stats"""
    mock_app = mocker.Mock()
    mock_statsd = mocker.Mock()
    mock_logger = mocker.Mock()

    with patch('app.utils.current_app', mock_app):
        mock_app.statsd_client = mock_statsd
        mock_app.logger = mock_logger

        with statsd_http('test'):
            pass

        mock_statsd.incr.assert_any_call('http.test.success')
        mock_statsd.incr.assert_any_call('http.success')
        mock_logger.debug.assert_called()


def test_statsd_http_exception_logs_stats_and_reraises(mocker):
    """The statsd_http context manager should re-raise exceptions and log exception stats"""
    mock_app = mocker.Mock()
    mock_statsd = mocker.Mock()
    mock_logger = mocker.Mock()

    with patch('app.utils.current_app', mock_app):
        mock_app.statsd_client = mock_statsd
        mock_app.logger = mock_logger

        with pytest.raises(Exception, match='simulated failure'):
            with statsd_http('test'):
                raise Exception('simulated failure')

        mock_statsd.incr.assert_any_call('http.test.exception')
        mock_statsd.incr.assert_any_call('http.exception')
        mock_logger.warning.assert_called()
