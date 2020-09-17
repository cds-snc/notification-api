import os

from datetime import datetime, timedelta

import pytz
from flask import current_app, url_for
from sqlalchemy import func
from notifications_utils.template import SMSMessageTemplate, WithSubjectTemplate, get_html_email_body

local_timezone = pytz.timezone(os.getenv("TIMEZONE", "America/Toronto"))


def pagination_links(pagination, endpoint, **kwargs):
    if 'page' in kwargs:
        kwargs.pop('page', None)
    links = {}
    if pagination.has_prev:
        links['prev'] = url_for(endpoint, page=pagination.prev_num, **kwargs)
    if pagination.has_next:
        links['next'] = url_for(endpoint, page=pagination.next_num, **kwargs)
        links['last'] = url_for(endpoint, page=pagination.pages, **kwargs)
    return links


def url_with_token(data, url, config, base_url=None):
    from notifications_utils.url_safe_token import generate_token
    token = generate_token(data, config['SECRET_KEY'], config['DANGEROUS_SALT'])
    base_url = (base_url or config['ADMIN_BASE_URL']) + url
    return base_url + token


def get_template_instance(template, values):
    from app.models import SMS_TYPE, EMAIL_TYPE, LETTER_TYPE
    return {
        SMS_TYPE: SMSMessageTemplate, EMAIL_TYPE: WithSubjectTemplate, LETTER_TYPE: WithSubjectTemplate
    }[template['template_type']](template, values)


def get_html_email_body_from_template(template_instance):
    from app.models import EMAIL_TYPE

    if template_instance.template_type != EMAIL_TYPE:
        return None

    return get_html_email_body(
        template_instance.content,
        template_instance.values,
    )


def get_local_timezone_midnight(date):
    """
     Gets the local timezones midnight
    """
    if hasattr(date, 'astimezone') is False:
        date = datetime.combine(date, datetime.min.time())
    local = date.astimezone(local_timezone)
    return local_timezone.localize(datetime.combine(
        local, datetime.min.time())).astimezone(pytz.UTC).replace(tzinfo=None)


def get_local_timezone_midnight_in_utc(date):
    """
     This function converts date to midnight as BST (British Standard Time) to UTC,
     the tzinfo is lastly removed from the datetime because the database stores the timestamps without timezone.
     :param date: the day to calculate the London midnight in UTC for
     :return: the datetime of London midnight in UTC, for example 2016-06-17 = 2016-06-16 23:00:00
    """
    return local_timezone.localize(datetime.combine(date, datetime.min.time())).astimezone(
        pytz.UTC).replace(
        tzinfo=None)


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
        func.timezone(os.getenv("TIMEZONE", "America/Toronto"), func.timezone("UTC", column))
    )


def get_public_notify_type_text(notify_type, plural=False):
    from app.models import (SMS_TYPE, UPLOAD_DOCUMENT, PRECOMPILED_LETTER)
    notify_type_text = notify_type
    if notify_type == SMS_TYPE:
        notify_type_text = 'text message'
    if notify_type == UPLOAD_DOCUMENT:
        notify_type_text = 'document'
    if notify_type == PRECOMPILED_LETTER:
        notify_type_text = 'precompiled letter'

    return '{}{}'.format(notify_type_text, 's' if plural else '')


def midnight_n_days_ago(number_of_days):
    """
    Returns midnight a number of days ago. Takes care of daylight savings etc.
    """
    return get_local_timezone_midnight_in_utc(datetime.utcnow() - timedelta(days=number_of_days))


def escape_special_characters(string):
    for special_character in ('\\', '_', '%', '/'):
        string = string.replace(
            special_character,
            r'\{}'.format(special_character)
        )
    return string


def email_address_is_nhs(email_address):
    return email_address.lower().endswith((
        '@nhs.uk', '@nhs.net', '.nhs.uk', '.nhs.net',
    ))


def update_dct_to_str(update_dct, lang):
    if lang not in ['EN', 'FR']:
        raise NotImplementedError

    values = {
        'EN': {
            'password': 'password',
            'name': 'name',
            'email_address': 'email address',
            'mobile_number': 'mobile number',
            'auth_type': 'auth type',
            'security_key_created': 'security key added',
            'security_key_deleted': 'security key removed',
        },
        'FR': {
            'password': 'mot de passe',
            'name': 'nom complet',
            'email_address': 'adresse courriel',
            'mobile_number': 'téléphone cellulaire',
            'auth_type': "méthode d'authentification",
            'security_key_created': 'clé de sécurité ajoutée',
            'security_key_deleted': 'clé de sécurité retirée',
        }
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
        current_app.config['HC_EN_SERVICE_ID'],
        current_app.config['HC_FR_SERVICE_ID'],
        current_app.config['BULK_SEND_TEST_SERVICE_ID'],
    ]

    if str(service_id) in bulk_sending_services:
        return int(current_app.config['CSV_MAX_ROWS_BULK_SEND'])
    return int(current_app.config['CSV_MAX_ROWS'])
