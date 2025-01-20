from datetime import datetime, timedelta, timezone
from itertools import islice

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from notifications_utils.timezones import convert_utc_to_local_timezone

from app import annual_limit_client, notify_celery
from app.config import QueueNames
from app.cronitor import cronitor
from app.dao.annual_limits_data_dao import (
    fetch_quarter_cummulative_stats,
    get_all_quarters,
    get_previous_quarter,
    insert_quarter_data,
)
from app.dao.fact_billing_dao import fetch_billing_data_for_day, update_fact_billing
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_for_day,
    fetch_quarter_data,
    update_fact_notification_status,
)
from app.dao.users_dao import get_services_for_all_users
from app.models import Service
from app.user.rest import send_annual_usage_data


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
    current_app.logger.info("create-nightly-notification-status started for {} ".format(day_start))
    for i in range(0, 4):
        process_day = day_start - timedelta(days=i)
        current_app.logger.info(
            "create-nightly-notification-status-for-day called from higher level job for day {} ".format(process_day)
        )
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
    chunk_size = 10
    iter_service_ids = iter(service_ids)
    current_app.logger.info("create-nightly-notification-status-for-day STARTED for day {} ".format(process_day))

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
            # TODO: FF_ANNUAL_LIMIT removal
            if current_app.config["FF_ANNUAL_LIMIT"]:
                annual_limit_client.reset_all_notification_counts(chunk)

        except Exception as e:
            current_app.logger.error(
                "create-nightly-notification-status-for-day task failed for day: {}, for service_ids: {}. Error: {}".format(
                    process_day, chunk, e
                )
            )


@notify_celery.task(name="insert-quarter-data-for-annual-limits")
@statsd(namespace="tasks")
def insert_quarter_data_for_annual_limits(process_day=None):
    """
    This function gets all the service ids and fetches all the notification_count
    for the given quarter for the service_ids. It then inserts that data
    into the annaual_limits_data_table.

    The process_day determines which quarter to fetch data for.
    This is based on the schedule of this task. The task is scheduled to at the start of the new quarter.
    """
    process_day = process_day if process_day else datetime.now()
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


def _format_number(number, use_space=False):
    if use_space:
        return "{:,}".format(number).replace(",", " ")
    return "{:,}".format(number)


def _create_quarterly_email_markdown_list(service_info, service_ids, cummulative_data_dict):
    """
    This function creates a markdown list of the service names and their email and sms usage

    Example:
    ## Notify
    Emails: you’ve sent 5,000 out of 100,000 (5%)
    Text messages: you’ve sent 1,000 out of 2,000 (50%)
    """
    markdown_list_en = ""
    markdown_list_fr = ""
    for service_id in service_ids:
        service_data = cummulative_data_dict.get(str(service_id), {})
        service_name, email_annual_limit, sms_annual_limit = service_info[service_id]
        email_count = service_data.get("email", 0)
        sms_count = service_data.get("sms", 0)

        markdown_list_en += f"## {service_name} \n"
        markdown_list_fr += f"## {service_name} \n"

        email_percentage = round(float(email_count / email_annual_limit), 4) * 100 if email_count else 0
        email_count_en = _format_number(email_count)
        email_annual_limit_en = _format_number(email_annual_limit)
        email_count_fr = _format_number(email_count, use_space=True)
        email_annual_limit_fr = _format_number(email_annual_limit, use_space=True)
        markdown_list_en += f"Emails: you've sent {email_count_en} out of {email_annual_limit_en} ({email_percentage}%)\n"
        markdown_list_fr += f"Courriels: {email_count_fr} envoyés sur {email_annual_limit_fr} ({email_percentage}%)\n"

        sms_percentage = round(float(sms_count / sms_annual_limit), 4) * 100 if sms_count else 0
        sms_count_en = _format_number(sms_count)
        sms_annual_limit_en = _format_number(sms_annual_limit)
        sms_count_fr = _format_number(sms_count, use_space=True)
        sms_annual_limit_fr = _format_number(sms_annual_limit, use_space=True)
        markdown_list_en += f"Text messages: you've sent {sms_count_en} out of {sms_annual_limit_en} ({sms_percentage}%)\n"
        markdown_list_fr += f"Messages texte : {sms_count_fr} envoyés sur {sms_annual_limit_fr} ({sms_percentage}%)\n"

        markdown_list_en += "\n"
        markdown_list_fr += "\n"
    return markdown_list_en, markdown_list_fr


@notify_celery.task(name="send-quarterly-email")
@statsd(namespace="tasks")
def send_quarter_email(process_date=None):
    process_date = process_date if process_date else datetime.now()  # this is the day the task is run
    service_info = {x.id: (x.name, x.email_annual_limit, x.sms_annual_limit) for x in Service.query.all()}

    user_service_array = get_services_for_all_users()
    quarters_list = get_all_quarters(process_date)
    chunk_size = 50
    iter_user_service_array = iter(user_service_array)
    start_year = int(quarters_list[0].split("-")[-1])
    end_year = start_year + 1

    while True:
        chunk = list(islice(iter_user_service_array, chunk_size))

        if not chunk:
            current_app.logger.info("send_quarter_email completed {} ".format(datetime.now(timezone.utc).date()))
            break

        try:
            all_service_ids = set()
            for _, _, services in chunk:
                all_service_ids.update(services)
            all_service_ids = list(all_service_ids)
            cummulative_data = fetch_quarter_cummulative_stats(quarters_list, all_service_ids)
            cummulative_data_dict = {str(c_data_id): c_data for c_data_id, c_data in cummulative_data}
            for user_id, _, service_ids in chunk:
                markdown_list_en, markdown_list_fr = _create_quarterly_email_markdown_list(
                    service_info, service_ids, cummulative_data_dict
                )
                send_annual_usage_data(user_id, start_year, end_year, markdown_list_en, markdown_list_fr)
                current_app.logger.info("send_quarter_email task completed for user {} ".format(user_id))
        except Exception as e:
            current_app.logger.error("send_quarter_email task failed for for user {} . Error: {}".format(user_id, e))
            continue
