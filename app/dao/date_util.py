import os
from datetime import date, datetime, time, timedelta, timezone

import pytz
from notifications_utils.strftime_codes import no_pad_month
from notifications_utils.timezones import convert_local_timezone_to_utc


def get_months_for_financial_year(year):
    return [
        convert_local_timezone_to_utc(month)
        for month in (get_months_for_year(4, 13, year) + get_months_for_year(1, 4, year + 1))
        if convert_local_timezone_to_utc(month) < datetime.now()
    ]


def get_months_for_year(start, end, year):
    return [datetime(year, month, 1) for month in range(start, end)]


def get_financial_year(year):
    return get_april_fools(year), get_april_fools(year + 1) - timedelta(microseconds=1)


def get_current_financial_year():
    now = datetime.utcnow()
    current_month = int(now.strftime(no_pad_month()))
    current_year = int(now.strftime("%Y"))
    year = current_year if current_month > 3 else current_year - 1
    return get_financial_year(year)


def get_april_fools(year):
    """
    This function converts the start of the financial year April 1, 00:00 as BST (British Standard Time) to UTC,
    the tzinfo is lastly removed from the datetime because the database stores the timestamps without timezone.
    :param year: the year to calculate the April 1, 00:00 BST for
    :return: the datetime of April 1 for the given year, for example 2016 = 2016-03-31 23:00:00
    """
    return (
        pytz.timezone(os.getenv("TIMEZONE", "America/Toronto"))
        .localize(datetime(year, 4, 1, 0, 0, 0))
        .astimezone(pytz.UTC)
        .replace(tzinfo=None)
    )


def get_month_start_and_end_date_in_utc(month_year):
    """
    This function return the start and date of the month_year as UTC,
    :param month_year: the datetime to calculate the start and end date for that month
    :return: start_date, end_date, month
    """
    import calendar

    _, num_days = calendar.monthrange(month_year.year, month_year.month)
    first_day = datetime(month_year.year, month_year.month, 1, 0, 0, 0)
    last_day = datetime(month_year.year, month_year.month, num_days, 23, 59, 59, 99999)
    return convert_local_timezone_to_utc(first_day), convert_local_timezone_to_utc(last_day)


def get_current_financial_year_start_year():
    now = datetime.now()
    financial_year_start = now.year
    start_date, end_date = get_financial_year(now.year)
    if now < start_date:
        financial_year_start = financial_year_start - 1
    return financial_year_start


def get_financial_year_for_datetime(start_date):
    if type(start_date) is date:
        start_date = datetime.combine(start_date, time.min)

    year = int(start_date.strftime("%Y"))
    if start_date < get_april_fools(year):
        return year - 1
    else:
        return year


def get_midnight(datetime: datetime) -> datetime:
    return datetime.replace(hour=0, minute=0, second=0, microsecond=0)


def tz_aware_utc_now() -> datetime:
    """
    Returns a localized, EST/EDT timezone aware, UTC now datetime.
    Call dst() on the returned object to determine daylight savings status.
    """
    return pytz.utc.localize(datetime.utcnow())


def tz_aware_midnight_n_days_ago(days_ago: int = 1) -> datetime:
    """
    Returns an EST/EDT aware UTC midnight date a number of days ago.
    """
    est = pytz.timezone("US/Eastern")
    return est.localize(tz_aware_utc_now().replace(tzinfo=None) - timedelta(days=days_ago))


def utc_midnight_n_days_ago(number_of_days):
    """
    Returns utc midnight a number of days ago.
    """
    return get_midnight(datetime.utcnow() - timedelta(days=number_of_days))


def get_query_date_based_on_retention_period(retention_period):
    """
    Computes a date to be used when querying for notifications based on retention period
    """
    return datetime.combine(datetime.now(timezone.utc) - timedelta(days=retention_period), time.max)
