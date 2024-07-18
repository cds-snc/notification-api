from urllib.parse import quote

from flask import current_app

from app.models import Notification


NOTIFICATION_API_GA4_GET_ENDPOINT = 'ga4/open-email-tracking'

GA4_PIXEL_TRACKING_NAME = 'email_open'
GA4_PIXEL_TRACKING_SOURCE = 'vanotify'
GA4_PIXEL_TRACKING_MEDIUM = 'email'


def build_dynamic_ga4_pixel_tracking_url(notification: Notification) -> str:
    """
    Constructs a dynamic URL that contains information on the notification email being sent.
    The dynamic URL is used for pixel tracking and sends a request to our application when
    email is opened.

    :param notification: The notification object containing template and service details.
    :return: A dynamically constructed URL string.
    """

    url = (
        f'{current_app.config["PUBLIC_DOMAIN"]}'
        f'{NOTIFICATION_API_GA4_GET_ENDPOINT}?'
        f'campaign={quote(notification.template.name)}&campaign_id={quote(str(notification.template.id))}&'
        f'name={quote(GA4_PIXEL_TRACKING_NAME)}&source={quote(GA4_PIXEL_TRACKING_SOURCE)}&medium={quote(GA4_PIXEL_TRACKING_MEDIUM)}&'
        f'content={quote(notification.service.name)}/{quote(str(notification.service.id))}/{quote(str(notification.id))}'
    )
    current_app.logger.debug('Generated Google Analytics 4 pixel URL: %s', url)
    return url
