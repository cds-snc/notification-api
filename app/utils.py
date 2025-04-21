import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Union
from uuid import UUID, uuid4

from flask import current_app, url_for
from notifications_utils.template import HTMLEmailTemplate, SMSMessageTemplate, WithSubjectTemplate, get_html_email_body
from notifications_utils.url_safe_token import generate_token
import pytz
from sqlalchemy import func

from app.constants import (
    BRANDING_BOTH,
    BRANDING_ORG_BANNER,
    EMAIL_TYPE,
    LETTER_TYPE,
    PRECOMPILED_LETTER,
    PUSH_TYPE,
    SMS_TYPE,
    UPLOAD_DOCUMENT,
)
from app.feature_flags import is_gapixel_enabled
from app.googleanalytics.pixels import build_dynamic_ga4_pixel_tracking_url
from app.models import TemplateBase

local_timezone = pytz.timezone(os.getenv('TIMEZONE', 'America/New_York'))


def pagination_links(
    pagination,
    endpoint,
    **kwargs,
):
    if 'page' in kwargs:
        kwargs.pop('page', None)
    links = {}
    if pagination.has_prev:
        links['prev'] = url_for(endpoint, page=pagination.prev_num, **kwargs)
    if pagination.has_next:
        links['next'] = url_for(endpoint, page=pagination.next_num, **kwargs)
        links['last'] = url_for(endpoint, page=pagination.pages, **kwargs)
    return links


def url_with_token(
    data,
    url,
    config,
    base_url=None,
):
    token = generate_token(data, config['SECRET_KEY'], config['DANGEROUS_SALT'])
    base_url = (base_url or config['ADMIN_BASE_URL']) + url
    return base_url + token


def get_template_instance(
    template: dict,
    personalisation: dict,
):
    """
    Return an appropriate template instance from the notifications-utils repository.  This happens here
    in order to validate that POST data for sending a notification has the correct personalisation values.
    Note that the same process inefficiently happens again later, in Celery, when the message is sending.

    template - A dictionary of the attributes and values of a Template instance
    personalisation - personalization for a template instance
    """

    return {SMS_TYPE: SMSMessageTemplate, EMAIL_TYPE: WithSubjectTemplate, LETTER_TYPE: WithSubjectTemplate}[
        template['template_type']
    ](template, personalisation)


def get_html_email_body_from_template(template_instance):
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
    return (
        local_timezone.localize(datetime.combine(date, datetime.min.time())).astimezone(pytz.UTC).replace(tzinfo=None)
    )


def get_midnight_for_day_before(date):
    day_before = date - timedelta(1)
    return get_local_timezone_midnight_in_utc(day_before)


def get_local_timezone_month_from_utc_column(column):
    """
    Where queries need to count notifications by month it needs to be
    the month in BST (British Summer Time).
    The database stores all timestamps as UTC without the timezone.
     - First set the timezone on created_at to UTC
     - then convert the timezone to BST (or America/New_York)
     - lastly truncate the datetime to month with which we can group
       queries
    """
    return func.date_trunc(
        'month', func.timezone(os.getenv('TIMEZONE', 'America/New_York'), func.timezone('UTC', column))
    )


def get_public_notify_type_text(
    notify_type,
    plural=False,
):
    notify_type_text = notify_type
    if notify_type == SMS_TYPE:
        notify_type_text = 'text message'
    if notify_type == UPLOAD_DOCUMENT:
        notify_type_text = 'document'
    if notify_type == PRECOMPILED_LETTER:
        notify_type_text = 'precompiled letter'
    if notify_type == PUSH_TYPE:
        notify_type_text = 'push notification'

    return '{}{}'.format(notify_type_text, 's' if plural else '')


def midnight_n_days_ago(number_of_days):
    """
    Returns midnight a number of days ago. Takes care of daylight savings etc.
    """
    return get_local_timezone_midnight_in_utc(datetime.utcnow() - timedelta(days=number_of_days))


def escape_special_characters(string):
    for special_character in ('\\', '_', '%', '/'):
        string = string.replace(special_character, r'\{}'.format(special_character))
    return string


def update_dct_to_str(update_dct):
    str = '\n'
    for key in update_dct:
        str += '- {}'.format(key.replace('_', ' '))
        str += '\n'
    return str


def create_uuid() -> str:
    return str(uuid4())


def get_logo_url(base_url, logo_file):
    """
    Generate the URL for a logo file based on the configured asset bucket and domain.

    Args:
        base_url: Base URL (not used but kept for compatibility)
        logo_file: Filename of the logo

    Returns:
        str: The fully qualified URL to the logo
    """
    bucket = current_app.config['ASSET_UPLOAD_BUCKET_NAME']
    domain = current_app.config['ASSET_DOMAIN']
    return f'https://{bucket}.{domain}/{logo_file}'


def get_html_email_options(
    template: TemplateBase, notification_id: str = 'xx_notification_id_xx'
) -> Dict[str, Union[str, bool]]:
    """
    Generate HTML email options dictionary for email rendering.

    This function creates a dictionary of options that will be used when rendering HTML emails.
    It determines which branding elements to include based on the service's email_branding configuration.
    If email_branding is None, it will use the default banner.
    Otherwise, it will include branding elements like colors, logos, and text from the service's email_branding.

    If Google Analytics pixel tracking is enabled, it also adds a tracking URL to the options.

    Args:
        template: The template object that contains a reference to the service
                with branding configuration
        notification_id: The ID of the notification (default is a placeholder)

    Returns:
        Dict[str, Union[str, bool]]: A dictionary containing HTML email options including:
            - default_banner: Whether to use the default banner
            - brand_banner: Whether to use the custom brand banner
            - brand_colour: The brand color (if available)
            - brand_logo: URL to the brand logo (if available)
            - brand_text: The brand text (if available)
            - brand_name: The brand name (if available)
            - ga4_open_email_event_url: Google Analytics tracking URL (if enabled)
    """
    options_dict = {}
    if is_gapixel_enabled(current_app):
        options_dict['ga4_open_email_event_url'] = build_dynamic_ga4_pixel_tracking_url(notification_id)

    service = template.service
    if service.email_branding is None:
        options_dict.update({'default_banner': True, 'brand_banner': False})
    else:
        logo_url = (
            get_logo_url(current_app.config['ADMIN_BASE_URL'], service.email_branding.logo)
            if service.email_branding.logo
            else None
        )

        options_dict.update(
            {
                'default_banner': service.email_branding.brand_type == BRANDING_BOTH,
                'brand_banner': service.email_branding.brand_type == BRANDING_ORG_BANNER,
                'brand_colour': service.email_branding.colour,
                'brand_logo': logo_url,
                'brand_text': service.email_branding.text,
                'brand_name': service.email_branding.name,
            }
        )

    return options_dict


def generate_html_email_content(template) -> Optional[str]:
    """
    Generate HTML content for an email template if applicable.

    Args:
        template: The template object that contains content and subject fields

    Returns:
        str: HTML content for the template if it's an email template,
             None otherwise
    """

    content = None
    if template.template_type == EMAIL_TYPE:
        template_object = HTMLEmailTemplate(
            {
                'content': template.content,
                'subject': template.subject,
            },
            **get_html_email_options(template),
        )
        content = str(template_object)

    return content


def get_redis_retry_key(notification_id: str | UUID) -> str:
    """This key is referenced in multiple places so warranted a function.

    Args:
        notification_id (str | UUID): Notification object's id

    Returns:
        str: redis key for this notification
    """
    return f'notification-carrier-sms-retry-count-{notification_id}'
