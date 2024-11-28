import os
from datetime import datetime, timedelta
from typing import Any

import pytz
from flask import current_app, url_for
from notifications_utils.template import (
    SMSMessageTemplate,
    WithSubjectTemplate,
    get_html_email_body,
)
from sqlalchemy import func

from app.config import Priorities, QueueNames

local_timezone = pytz.timezone(os.getenv("TIMEZONE", "America/Toronto"))

DELIVERED_STATUSES = ["delivered", "sent", "returned-letter"]
FAILURE_STATUSES = [
    "failed",
    "temporary-failure",
    "permanent-failure",
    "technical-failure",
    "virus-scan-failed",
    "validation-failed",
]


def pagination_links(pagination, endpoint, **kwargs):
    if "page" in kwargs:
        kwargs.pop("page", None)
    links = {}
    if pagination.has_prev:
        links["prev"] = url_for(endpoint, page=pagination.prev_num, **kwargs)
    if pagination.has_next:
        links["next"] = url_for(endpoint, page=pagination.next_num, **kwargs)
        links["last"] = url_for(endpoint, page=pagination.pages, **kwargs)
    return links


def url_with_token(data, url, config, base_url=None):
    from notifications_utils.url_safe_token import generate_token

    token = generate_token(data, config["SECRET_KEY"])
    base_url = (base_url or config["ADMIN_BASE_URL"]) + url
    return base_url + token


def get_template_instance(template, values):
    from app.models import EMAIL_TYPE, LETTER_TYPE, SMS_TYPE

    return {SMS_TYPE: SMSMessageTemplate, EMAIL_TYPE: WithSubjectTemplate, LETTER_TYPE: WithSubjectTemplate}[
        template["template_type"]
    ](template, values)


def get_delivery_queue_for_template(template):
    return QueueNames.DELIVERY_QUEUES[template.template_type][Priorities.to_lmh(template.process_type)]


def get_html_email_body_from_template(template_instance):
    from app.models import EMAIL_TYPE

    if template_instance.template_type != EMAIL_TYPE:
        return None

    return get_html_email_body(
        template_instance.content,
        template_instance.values,
    )


def get_local_timezone_midnight(date: datetime):
    """
    Gets the local timezones midnight
    """
    if hasattr(date, "astimezone") is False:
        date = datetime.combine(date, datetime.min.time())
    local = date.astimezone(local_timezone)
    naive_min_time = datetime.combine(local, datetime.min.time())
    local_min_time = local_timezone.localize(naive_min_time)
    as_utc = local_min_time.astimezone(pytz.UTC)
    return as_utc.replace(tzinfo=None)


def get_local_timezone_midnight_in_utc(date):
    """
    This function converts date to midnight as BST (British Standard Time) to UTC,
    the tzinfo is lastly removed from the datetime because the database stores the timestamps without timezone.
    :param date: the day to calculate the London midnight in UTC for
    :return: the datetime of London midnight in UTC, for example 2016-06-17 = 2016-06-16 23:00:00
    """
    return local_timezone.localize(datetime.combine(date, datetime.min.time())).astimezone(pytz.UTC).replace(tzinfo=None)


def get_midnight_for_day_before(date):
    day_before = date - timedelta(1)
    return get_local_timezone_midnight_in_utc(day_before)


def get_local_timezone_month_from_utc_column(column):
    """
    Where queries need to count notifications by month it needs to be
    the month in BST (British Summer Time).
    The database stores all timestamps as UTC without the timezone.
     - First set the timezone on created_at to UTC
     - then convert the timezone to BST (or America/Toronto)
     - lastly truncate the datetime to month with which we can group
       queries
    """
    return func.date_trunc(
        "month",
        func.timezone(os.getenv("TIMEZONE", "America/Toronto"), func.timezone("UTC", column)),
    )


def get_public_notify_type_text(notify_type, plural=False):
    from app.models import PRECOMPILED_LETTER, SMS_TYPE, UPLOAD_DOCUMENT

    notify_type_text = notify_type
    if notify_type == SMS_TYPE:
        notify_type_text = "text message"
    if notify_type == UPLOAD_DOCUMENT:
        notify_type_text = "document"
    if notify_type == PRECOMPILED_LETTER:
        notify_type_text = "precompiled letter"

    return "{}{}".format(notify_type_text, "s" if plural else "")


def midnight_n_days_ago(number_of_days):
    """
    Returns midnight a number of days ago. Takes care of daylight savings etc.
    """
    return get_local_timezone_midnight_in_utc(datetime.utcnow() - timedelta(days=number_of_days))


def escape_special_characters(string):
    for special_character in ("\\", "_", "%", "/"):
        string = string.replace(special_character, r"\{}".format(special_character))
    return string


def email_address_is_nhs(email_address):
    return email_address.lower().endswith(
        (
            "@nhs.uk",
            "@nhs.net",
            ".nhs.uk",
            ".nhs.net",
        )
    )


def update_dct_to_str(update_dct, lang):
    if lang not in ["EN", "FR"]:
        raise NotImplementedError

    values = {
        "EN": {
            "password": "password",
            "name": "name",
            "email_address": "email address",
            "mobile_number": "mobile number",
            "auth_type": "auth type",
            "security_key_created": "security key added",
            "security_key_deleted": "security key removed",
        },
        "FR": {
            "password": "mot de passe",
            "name": "nom complet",
            "email_address": "adresse courriel",
            "mobile_number": "téléphone cellulaire",
            "auth_type": "méthode d'authentification",
            "security_key_created": "clé de sécurité ajoutée",
            "security_key_deleted": "clé de sécurité retirée",
        },
    }

    content = "\n"
    for key in update_dct:
        try:
            key_name = values[lang][key]
        except KeyError:
            key_name = key.replace("_", " ")
        content += "- {}".format(key_name)
        content += "\n"
    return content


def get_csv_max_rows(service_id):
    bulk_sending_services = [
        current_app.config["HC_EN_SERVICE_ID"],
        current_app.config["HC_FR_SERVICE_ID"],
        current_app.config["BULK_SEND_TEST_SERVICE_ID"],
    ]

    if str(service_id) in bulk_sending_services:
        return int(current_app.config["CSV_MAX_ROWS_BULK_SEND"])
    return int(current_app.config["CSV_MAX_ROWS"])


def get_logo_url(logo_file):
    return f"https://{current_app.config['ASSET_DOMAIN']}/{logo_file}"


def get_document_url(lang: str, path: str):
    return f'https://{current_app.config["DOCUMENTATION_DOMAIN"]}/{lang}/{path}'


def is_blank(content: Any) -> bool:
    content = str(content)
    return not content or content.isspace()


def get_limit_reset_time_et() -> dict[str, str]:
    """
    This function gets the time when the daily limit resets (UTC midnight)
    and returns this formatted in eastern time. This will either be 7PM or 8PM,
    depending on the time of year."""

    now = datetime.now()
    one_day = timedelta(1.0)
    next_midnight = datetime(now.year, now.month, now.day) + one_day

    utc = pytz.timezone("UTC")
    et = pytz.timezone("US/Eastern")

    next_midnight_utc = next_midnight.astimezone(utc)
    next_midnight_utc_in_et = next_midnight_utc.astimezone(et)

    limit_reset_time_et = {"12hr": next_midnight_utc_in_et.strftime("%-I%p"), "24hr": next_midnight_utc_in_et.strftime("%H")}
    return limit_reset_time_et


def prepare_notification_counts_for_seeding(notification_counts: list) -> dict:
    """Utility method that transforms a list of notification counts into a dictionary, mapping notification counts by type and success/failure.
    Used to seed notification counts in Redis for annual limits.
    e.g.
    ```
    [(datetime, 'email', 'sent', 1),
    (datetime, 'sms', 'sent', 2)]
    ```
    Becomes:
    ```
    {'email_sent': 1, 'sms_sent': 2}
    ```
    Args:
        notification_counts (list): A list of tuples containing (date, notification_type, status, count)

    Returns:
        dict: That acts as a mapping to build the notification counts in Redis
    """
    return {
        f"{notification_type}_{'delivered' if status in DELIVERED_STATUSES else 'failed'}": count
        for _, notification_type, status, count in notification_counts
        if status in DELIVERED_STATUSES or status in FAILURE_STATUSES
    }


def get_fiscal_year(current_date=None):
    """
    Determine the fiscal year for a given date.

    Args:
        current_date (datetime.date, optional): The date to determine the fiscal year for.
                                                Defaults to today's date.

    Returns:
        int: The fiscal year (starting year).
    """
    if current_date is None:
        current_date = datetime.today()

    # Fiscal year starts on April 1st
    fiscal_year_start_month = 4
    if current_date.month >= fiscal_year_start_month:
        return current_date.year
    else:
        return current_date.year - 1


def get_fiscal_dates(current_date=None, year=None):
    """
    Determine the start and end dates of the fiscal year for a given date or year.
    If no parameters are passed into the method, the fiscal year for the current date will be determined.

    Args:
        current_date (datetime.date, optional): The date to determine the fiscal year for.
        year (int, optional): The year to determine the fiscal year for.

    Returns:
        tuple: A tuple containing the start and end dates of the fiscal year (datetime.date).
    """
    if current_date and year:
        raise ValueError("Only one of current_date or year should be provided.")

    if not current_date and not year:
        current_date = datetime.today()

    # Fiscal year starts on April 1st
    fiscal_year_start_month = 4
    fiscal_year_start_day = 1

    if current_date:
        if current_date.month >= fiscal_year_start_month:
            fiscal_year_start = datetime(current_date.year, fiscal_year_start_month, fiscal_year_start_day)
            fiscal_year_end = datetime(current_date.year + 1, fiscal_year_start_month - 1, 31)  # March 31 of the next year
        else:
            fiscal_year_start = datetime(current_date.year - 1, fiscal_year_start_month, fiscal_year_start_day)
            fiscal_year_end = datetime(current_date.year, fiscal_year_start_month - 1, 31)  # March 31 of the current year

    if year:
        fiscal_year_start = datetime(year, fiscal_year_start_month, fiscal_year_start_day)
        fiscal_year_end = datetime(year + 1, fiscal_year_start_month - 1, 31)

    return fiscal_year_start, fiscal_year_end
