from flask import current_app

from app.models import Notification


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
        f'{current_app.config["NOTIFICATION_API_GA4_GET_ENDPOINT"]}/{str(notification.id)}'
    )
    current_app.logger.debug('Generated Google Analytics 4 pixel URL: %s', url)
    return url
