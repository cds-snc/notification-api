from datetime import datetime, timedelta, timezone
from itertools import islice

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from notifications_utils.timezones import convert_utc_to_local_timezone

from app import notify_celery
from app.config import QueueNames
from app.cronitor import cronitor
from app.dao.fact_billing_dao import fetch_billing_data_for_day, update_fact_billing
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_for_day,
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
