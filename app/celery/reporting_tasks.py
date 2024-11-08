from datetime import datetime, timedelta, timezone
from itertools import islice

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from notifications_utils.timezones import convert_utc_to_local_timezone

from app import notify_celery
from app.config import QueueNames
from app.cronitor import cronitor
from app.dao.annual_limits_data_dao import get_previous_quarter, insert_quarter_data
from app.dao.fact_billing_dao import fetch_billing_data_for_day, update_fact_billing
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_for_day,
    fetch_quarter_data,
    update_fact_notification_status,
)
from app.models import Service


@notify_celery.task(name="create-nightly-billing")
@cronitor("create-nightly-billing")
@statsd(namespace="tasks")
def create_nightly_billing(day_start=None):
    # day_start is a datetime.date() object. e.g.
    # up to 4 days of data counting back from day_start is consolidated
    if day_start is None:
        day_start = convert_utc_to_local_timezone(datetime.utcnow()).date() - timedelta(days=1)
    else:
        # When calling the task its a string in the format of "YYYY-MM-DD"
        day_start = datetime.strptime(day_start, "%Y-%m-%d").date()
    for i in range(0, 4):
        process_day = day_start - timedelta(days=i)

        create_nightly_billing_for_day.apply_async(kwargs={"process_day": process_day.isoformat()}, queue=QueueNames.REPORTING)


@notify_celery.task(name="create-nightly-billing-for-day")
@statsd(namespace="tasks")
def create_nightly_billing_for_day(process_day):
    process_day = datetime.strptime(process_day, "%Y-%m-%d").date()

    start = datetime.utcnow()
    transit_data = fetch_billing_data_for_day(process_day=process_day)
    end = datetime.utcnow()

    current_app.logger.info("create-nightly-billing-for-day {} fetched in {} seconds".format(process_day, (end - start).seconds))

    for data in transit_data:
        update_fact_billing(data, process_day)

    current_app.logger.info(
        "create-nightly-billing-for-day task complete. {} rows updated for day: {}".format(len(transit_data), process_day)
    )


@notify_celery.task(name="create-nightly-notification-status")
@cronitor("create-nightly-notification-status")
@statsd(namespace="tasks")
def create_nightly_notification_status(day_start=None):
    # day_start is a datetime.date() object. e.g.
    # 4 days of data counting back from day_start is consolidated
    if day_start is None:
        day_start = convert_utc_to_local_timezone(datetime.utcnow()).date() - timedelta(days=1)
    else:
        # When calling the task its a string in the format of "YYYY-MM-DD"
        day_start = datetime.strptime(day_start, "%Y-%m-%d").date()
    for i in range(0, 4):
        process_day = day_start - timedelta(days=i)

        create_nightly_notification_status_for_day.apply_async(
            kwargs={"process_day": process_day.isoformat()}, queue=QueueNames.REPORTING
        )


@notify_celery.task(name="create-nightly-notification-status-for-day")
@statsd(namespace="tasks")
def create_nightly_notification_status_for_day(process_day):
    """
    This function gets all the service ids and fetches the notification status for the given day.
    It does it in chunks of 20 service ids at a time.

    Args:
        process_day (_type_): datetime object
    """
    process_day = datetime.strptime(process_day, "%Y-%m-%d").date()
    service_ids = [x.id for x in Service.query.all()]
    chunk_size = 20
    iter_service_ids = iter(service_ids)

    while True:
        chunk = list(islice(iter_service_ids, chunk_size))

        if not chunk:
            current_app.logger.info(
                "create-nightly-notification-status-for-day job completed for process_day {} on {}".format(
                    process_day, datetime.now(timezone.utc).date()
                )
            )
            break

        try:
            start = datetime.now(timezone.utc)
            transit_data = fetch_notification_status_for_day(process_day=process_day, service_ids=chunk)
            end = datetime.now(timezone.utc)
            current_app.logger.info(
                "create-nightly-notification-status-for-day {} fetched in {} seconds".format(process_day, (end - start).seconds)
            )
            update_fact_notification_status(transit_data, process_day, service_ids=chunk)

            current_app.logger.info(
                "create-nightly-notification-status-for-day task complete: {} rows updated for day: {}, for service_ids: {}".format(
                    len(transit_data), process_day, chunk
                )
            )
        except Exception as e:
            current_app.logger.error(
                "create-nightly-notification-status-for-day task failed for day: {}, for service_ids: {}. Error: {}".format(
                    process_day, chunk, e
                )
            )


@notify_celery.task(name="insert-quarter-data-for-annual-limits")
@statsd(namespace="tasks")
def insert_quarter_data_for_annual_limits(process_day):
    """
    This function gets all the service ids and fetches all the notification_count
    for the given quarter for the service_ids. It then inserts that data
    into the annaual_limits_data_table.

    The process_day determines which quarter to fetch data for.

    Args:
        process_day = datetime object
    """

    quarter, dates = get_previous_quarter(process_day)
    start_date = dates[0]
    end_date = dates[1]

    service_info = {x.id: (x.email_annual_limit, x.sms_annual_limit) for x in Service.query.all()}
    service_ids = [service_id for service_id in service_info]
    chunk_size = 20
    iter_service_ids = iter(service_ids)

    while True:
        chunk = list(islice(iter_service_ids, chunk_size))

        if not chunk:
            current_app.logger.info(
                "insert_quarter_data_for_annual_limits completed for quarter {} on {}".format(
                    quarter, datetime.now(timezone.utc).date()
                )
            )
            break

        try:
            start = datetime.now(timezone.utc)
            transit_data = fetch_quarter_data(start_date, end_date, service_ids=chunk)
            end = datetime.now(timezone.utc)
            current_app.logger.info(
                "fetch_quarter_data_for_annual_limits for time period {} to {} fetched in {} seconds".format(
                    start_date, end_date, (end - start).seconds
                )
            )
            insert_quarter_data(transit_data, quarter, service_info)

            current_app.logger.info(
                "insert_quarter_data task complete: {} rows updated for time period {} to {} for service_ids {}".format(
                    len(transit_data), start_date, end_date, chunk
                )
            )
        except Exception as e:
            current_app.logger.error(
                "insert_quarter_data_for_annual_limits task failed for for time period {} to {} for service_ids {}. Error: {}".format(
                    start_date, end_date, chunk, e
                )
            )
