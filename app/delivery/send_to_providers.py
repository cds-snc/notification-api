import base64
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

import phonenumbers
from flask import current_app
from notifications_utils.recipients import (
    validate_and_format_email_address,
    validate_and_format_phone_number,
)
from notifications_utils.template import (
    HTMLEmailTemplate,
    PlainTextEmailTemplate,
    SMSMessageTemplate,
)
from unidecode import unidecode
from urllib3 import PoolManager
from urllib3.util import Retry

from app import bounce_rate_client, clients, document_download_client, statsd_client
from app.celery.research_mode_tasks import send_email_response, send_sms_response
from app.clients.sms import SmsSendingVehicles
from app.config import Config
from app.dao.notifications_dao import dao_update_notification
from app.dao.provider_details_dao import (
    dao_toggle_sms_provider,
    get_provider_details_by_notification_type,
)
from app.dao.template_categories_dao import dao_get_template_category_by_id
from app.dao.templates_dao import dao_get_template_by_id
from app.exceptions import (
    DocumentDownloadException,
    InvalidUrlException,
    MalwareDetectedException,
    MalwareScanInProgressException,
    NotificationTechnicalFailureException,
)
from app.models import (
    BRANDING_BOTH_EN,
    BRANDING_BOTH_FR,
    BRANDING_ORG_BANNER_NEW,
    EMAIL_TYPE,
    KEY_TYPE_TEST,
    NOTIFICATION_CONTAINS_PII,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_VIRUS_SCAN_FAILED,
    PINPOINT_PROVIDER,
    SMS_TYPE,
    SNS_PROVIDER,
    BounceRateStatus,
    Notification,
    Service,
)
from app.utils import get_logo_url, is_blank


def send_sms_to_provider(notification):
    service = notification.service

    if not service.active:
        inactive_service_failure(notification=notification)
        return

    # If the notification was not sent already, the status should be created.
    if notification.status == "created":
        provider = provider_to_use(
            SMS_TYPE,
            notification.id,
            notification.to,
            notification.international,
            notification.reply_to_text,
            template_id=notification.template_id,
        )

        template_dict = dao_get_template_by_id(notification.template_id, notification.template_version).__dict__

        template = SMSMessageTemplate(
            template_dict,
            values=notification.personalisation,
            prefix=service.name,
            show_prefix=service.prefix_sms,
        )

        if is_blank(template):
            empty_message_failure(notification=notification)
            return

        if service.research_mode or notification.key_type == KEY_TYPE_TEST:
            notification.reference = send_sms_response(provider.get_name(), notification.to)
            update_notification_to_sending(notification, provider)

        elif (
            validate_and_format_phone_number(notification.to, international=notification.international)
            == Config.INTERNAL_TEST_NUMBER
        ):
            current_app.logger.info(f"notification {notification.id} sending to internal test number. Not sending to AWS")
            notification.reference = send_sms_response(provider.get_name(), notification.to)
            notification.billable_units = template.fragment_count
            update_notification_to_sending(notification, provider)

        else:
            try:
                template_category_id = template_dict.get("template_category_id")
                if current_app.config["FF_TEMPLATE_CATEGORY"] and template_category_id is not None:
                    sending_vehicle = SmsSendingVehicles(
                        dao_get_template_category_by_id(template_category_id).sms_sending_vehicle
                    )
                else:
                    sending_vehicle = None
                reference = provider.send_sms(
                    to=validate_and_format_phone_number(notification.to, international=notification.international),
                    content=str(template),
                    reference=str(notification.id),
                    sender=notification.reply_to_text,
                    template_id=notification.template_id,
                    service_id=notification.service_id,
                    sending_vehicle=sending_vehicle,
                )
            except Exception as e:
                notification.billable_units = template.fragment_count
                dao_update_notification(notification)
                dao_toggle_sms_provider(provider.name)
                raise e
            else:
                notification.reference = reference
                notification.billable_units = template.fragment_count
                if reference == "opted_out":
                    update_notification_to_opted_out(notification, provider)
                else:
                    update_notification_to_sending(notification, provider)

        # Record StatsD stats to compute SLOs
        statsd_client.timing_with_dates("sms.total-time", notification.sent_at, notification.created_at)
        statsd_key = f"sms.process_type-{template_dict['process_type']}"
        statsd_client.timing_with_dates(statsd_key, notification.sent_at, notification.created_at)
        statsd_client.incr(statsd_key)


def is_service_allowed_html(service: Service) -> bool:
    """
    If a service id is present in ALLOW_HTML_SERVICE_IDS, then they are allowed to put html
    in email templates.
    """
    return str(service.id) in current_app.config["ALLOW_HTML_SERVICE_IDS"]


# Prevent URL patterns like file:// ftp:// that may lead to security local file read vulnerabilities
def check_file_url(file_info: Dict[str, str], notification_id: UUID):
    if file_info.get("sending_method") == "attach":
        url_key = "direct_file_url"
    else:
        url_key = "url"

    if not file_info[url_key].lower().startswith("http"):
        current_app.logger.error(f"Notification {notification_id} contains an invalid {url_key} {file_info[url_key]}")
        raise InvalidUrlException


def check_for_malware_errors(document_download_response_code, notification):
    """
    Check verdict and download calls to the document-download-api will
    return error codes if the scan is in progress or if malware was detected.
    This function contains the logic for handling these errors.
    """

    # 423 "Locked" response is sent if malicious content was detected
    if document_download_response_code == 423:
        current_app.logger.info(
            f"Malicious content detected! Download and attachment failed for notification.id: {notification.id}"
        )
        # Update notification that it contains malware
        malware_failure(notification=notification)
    # 428 "Precondition Required" response is sent if the scan is still in progress
    elif document_download_response_code == 428:
        current_app.logger.info(f"Malware scan in progress, could not download files for notification.id: {notification.id}")
        # Throw error so celery will retry
        raise MalwareScanInProgressException
    # 408 "Request Timeout" response is sent if the scan does is not complete before it times out
    elif document_download_response_code == 408:
        current_app.logger.info(f"Malware scan timed out for notification.id: {notification.id}, send anyway")
        return
    elif document_download_response_code == 200:
        return
    # unexpected response code
    else:
        document_download_internal_error(notification=notification)


def check_service_over_bounce_rate(service_id: str):
    bounce_rate = bounce_rate_client.get_bounce_rate(service_id)
    bounce_rate_status = bounce_rate_client.check_bounce_rate_status(service_id)
    debug_data = bounce_rate_client.get_debug_data(service_id)
    current_app.logger.debug(
        f"Service id: {service_id} Bounce Rate: {bounce_rate} Bounce Status: {bounce_rate_status}, Debug Data: {debug_data}"
    )
    if bounce_rate_status == BounceRateStatus.CRITICAL.value:
        # TODO: Bounce Rate V2, raise a BadRequestError when bounce rate meets or exceeds critical threshold
        current_app.logger.warning(
            f"Service: {service_id} has met or exceeded a critical bounce rate threshold of 10%. Bounce rate: {bounce_rate}"
        )
    elif bounce_rate_status == BounceRateStatus.WARNING.value:
        current_app.logger.warning(
            f"Service: {service_id} has met or exceeded a warning bounce rate threshold of 5%. Bounce rate: {bounce_rate}"
        )


def mime_encoded_word_syntax(encoded_text="", charset="utf-8", encoding="B") -> str:
    """MIME encoded-word syntax is a way to encode non-ASCII characters in email headers.
    It is described here:
    https://docs.aws.amazon.com/ses/latest/dg/send-email-raw.html#send-email-mime-encoding-headers
    """
    return f"=?{charset}?{encoding}?{encoded_text}?="


def get_from_address(friendly_from: str, email_from: str, sending_domain: str) -> str:
    """
    This function returns the from_address or source in MIME encoded-word syntax
    friendly_from is the sender's display name and may contain accents so we need to encode it to base64
    email_from and sending_domain should be ASCII only
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ses/client/send_raw_email.html
    "If you want to use Unicode characters in the “friendly from” name, you must encode the “friendly from”
    name using MIME encoded-word syntax, as described in Sending raw email using the Amazon SES API."
    """
    friendly_from_b64 = base64.b64encode(friendly_from.encode()).decode("utf-8")
    friendly_from_mime = mime_encoded_word_syntax(encoded_text=friendly_from_b64, charset="utf-8", encoding="B")
    return f'"{friendly_from_mime}" <{unidecode(email_from)}@{unidecode(sending_domain)}>'


def send_email_to_provider(notification: Notification):
    current_app.logger.info(f"Sending email to provider for notification id {notification.id}")
    service = notification.service
    if not service.active:
        inactive_service_failure(notification=notification)
        return

    # If the notification was not sent already, the status should be created.
    if notification.status == "created":
        provider = provider_to_use(EMAIL_TYPE, notification.id)

        # Extract any file objects from the personalization
        file_keys = [k for k, v in (notification.personalisation or {}).items() if isinstance(v, dict) and "document" in v]
        attachments = []

        personalisation_data = notification.personalisation.copy()

        for key in file_keys:
            check_file_url(personalisation_data[key]["document"], notification.id)
            sending_method = personalisation_data[key]["document"].get("sending_method")
            direct_file_url = personalisation_data[key]["document"]["direct_file_url"]
            filename = personalisation_data[key]["document"].get("filename")
            mime_type = personalisation_data[key]["document"].get("mime_type")
            document_id = personalisation_data[key]["document"]["id"]
            scan_verdict_response = document_download_client.check_scan_verdict(service.id, document_id, sending_method)
            check_for_malware_errors(scan_verdict_response.status_code, notification)
            current_app.logger.info(f"scan_verdict for document_id {document_id} is {scan_verdict_response.json()}")
            if sending_method == "attach":
                try:
                    retries = Retry(total=5)
                    http = PoolManager(retries=retries)

                    response = http.request("GET", url=direct_file_url)
                    attachments.append(
                        {
                            "name": filename,
                            "data": response.data,
                            "mime_type": mime_type,
                        }
                    )
                except Exception as e:
                    current_app.logger.error(f"Could not download and attach {direct_file_url}\nException: {e}")
                    del personalisation_data[key]

            else:
                personalisation_data[key] = personalisation_data[key]["document"]["url"]

        template_dict = dao_get_template_by_id(notification.template_id, notification.template_version).__dict__

        # Local Jinja support - Add USE_LOCAL_JINJA_TEMPLATES=True to .env
        # Add a folder to the project root called 'jinja_templates'
        # with a copy of 'email_template.jinja2' from notification-utils repo
        debug_template_path = (
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if os.environ.get("USE_LOCAL_JINJA_TEMPLATES") == "True"
            else None
        )
        html_email = HTMLEmailTemplate(
            template_dict,
            values=personalisation_data,
            jinja_path=debug_template_path,
            allow_html=is_service_allowed_html(service),
            **get_html_email_options(service),
        )

        plain_text_email = PlainTextEmailTemplate(template_dict, values=personalisation_data)

        if current_app.config["SCAN_FOR_PII"]:
            contains_pii(notification, str(plain_text_email))

        current_app.logger.info(
            f"Trying to update notification id {notification.id} with service research {service.research_mode} or key type {notification.key_type}"
        )
        if service.research_mode or notification.key_type == KEY_TYPE_TEST:
            notification.reference = send_email_response(notification.to)
            update_notification_to_sending(notification, provider)
        elif notification.to == Config.INTERNAL_TEST_EMAIL_ADDRESS:
            current_app.logger.info(f"notification {notification.id} sending to internal test email address. Not sending to AWS")
            notification.reference = send_email_response(notification.to)
            update_notification_to_sending(notification, provider)
        else:
            if service.sending_domain is None or service.sending_domain.strip() == "":
                sending_domain = current_app.config["NOTIFY_EMAIL_DOMAIN"]
            else:
                sending_domain = service.sending_domain

            from_address = get_from_address(
                friendly_from=service.name, email_from=service.email_from, sending_domain=sending_domain
            )
            email_reply_to = notification.reply_to_text

            reference = provider.send_email(
                from_address,
                validate_and_format_email_address(notification.to),
                plain_text_email.subject,
                body=str(plain_text_email),
                html_body=str(html_email),
                reply_to_address=validate_and_format_email_address(email_reply_to) if email_reply_to else None,
                attachments=attachments,
            )
            check_service_over_bounce_rate(service.id)
            bounce_rate_client.set_sliding_notifications(service.id, str(notification.id))
            current_app.logger.info(f"Setting total notifications for service {service.id} in REDIS")
            current_app.logger.info(f"Notification id {notification.id} HAS BEEN SENT")
            notification.reference = reference
            update_notification_to_sending(notification, provider)
        current_app.logger.info(f"Notification id {notification.id} status in sending")

        # Record StatsD stats to compute SLOs
        statsd_client.timing_with_dates("email.total-time", notification.sent_at, notification.created_at)
        attachments_category = "with-attachments" if attachments else "no-attachments"
        statsd_key = f"email.{attachments_category}.process_type-{template_dict['process_type']}"
        statsd_client.timing_with_dates(statsd_key, notification.sent_at, notification.created_at)
        statsd_client.incr(statsd_key)


def update_notification_to_sending(notification, provider):
    notification.sent_at = datetime.utcnow()
    notification.sent_by = provider.get_name()
    notification.status = NOTIFICATION_SENT if notification.notification_type == "sms" else NOTIFICATION_SENDING
    dao_update_notification(notification)


def update_notification_to_opted_out(notification, provider):
    notification.sent_at = datetime.utcnow()
    notification.sent_by = provider.get_name()
    notification.status = NOTIFICATION_PERMANENT_FAILURE
    notification.provider_response = "Phone number is opted out"
    dao_update_notification(notification)


def provider_to_use(
    notification_type: str,
    notification_id: UUID,
    to: Optional[str] = None,
    international: bool = False,
    sender: Optional[str] = None,
    template_id: Optional[UUID] = None,
) -> Any:
    """
    Get the provider to use for sending the notification.
    SMS that are being sent with a dedicated number or internationally should not use Pinpoint.

    Args:
        notification_type (str): SMS or EMAIL.
        notification_id (UUID): id of notification. Just used for logging.
        to (str, optional): recipient. Defaults to None.
        international (bool, optional):  Flags whether or not the message recipient is outside Zone 1 (US / Canada / Caribbean). Defaults to False.
        sender (str, optional): reply_to_text to use. Defaults to None.
        template_id (str, optional): template_id to use. Defaults to None.

    Raises:
        Exception: No active providers.

    Returns:
        provider: Provider to use to send the notification.
    """

    has_dedicated_number = sender is not None and sender.startswith("+1")
    cannot_determine_recipient_country = False
    recipient_outside_canada = False
    sending_to_us_number = False
    if to is not None:
        match = next(iter(phonenumbers.PhoneNumberMatcher(to, "US")), None)
        if match is None:
            cannot_determine_recipient_country = True
        elif (
            phonenumbers.region_code_for_number(match.number) == "US"
        ):  # The US is a special case that needs to send from a US toll free number
            sending_to_us_number = True
        elif phonenumbers.region_code_for_number(match.number) != "CA":
            recipient_outside_canada = True
    using_sc_pool_template = template_id is not None and str(template_id) in current_app.config["AWS_PINPOINT_SC_TEMPLATE_IDS"]
    zone_1_outside_canada = recipient_outside_canada and not international
    do_not_use_pinpoint = (
        has_dedicated_number
        or sending_to_us_number
        or cannot_determine_recipient_country
        or zone_1_outside_canada
        or not current_app.config["AWS_PINPOINT_SC_POOL_ID"]
        or ((not current_app.config["AWS_PINPOINT_DEFAULT_POOL_ID"]) and not using_sc_pool_template)
    )
    if do_not_use_pinpoint:
        active_providers_in_order = [
            p
            for p in get_provider_details_by_notification_type(notification_type, international)
            if p.active and p.identifier != PINPOINT_PROVIDER
        ]
    else:
        active_providers_in_order = [
            p
            for p in get_provider_details_by_notification_type(notification_type, international)
            if p.active and p.identifier != SNS_PROVIDER
        ]

    if not active_providers_in_order:
        current_app.logger.error("{} {} failed as no active providers".format(notification_type, notification_id))
        raise Exception("No active {} providers".format(notification_type))

    return clients.get_client_by_name_and_type(active_providers_in_order[0].identifier, notification_type)


def get_html_email_options(service: Service):
    if service.email_branding is None:
        if service.default_branding_is_french is True:
            return {
                "fip_banner_english": False,
                "fip_banner_french": True,
                "logo_with_background_colour": False,
                "alt_text_en": None,
                "alt_text_fr": None,
            }
        else:
            return {
                "fip_banner_english": True,
                "fip_banner_french": False,
                "logo_with_background_colour": False,
                "alt_text_en": None,
                "alt_text_fr": None,
            }

    logo_url = get_logo_url(service.email_branding.logo) if service.email_branding.logo else None

    return {
        "fip_banner_english": service.email_branding.brand_type == BRANDING_BOTH_EN,
        "fip_banner_french": service.email_branding.brand_type == BRANDING_BOTH_FR,
        "logo_with_background_colour": service.email_branding.brand_type == BRANDING_ORG_BANNER_NEW,
        "brand_colour": service.email_branding.colour,
        "brand_logo": logo_url,
        "brand_text": service.email_branding.text,
        "brand_name": service.email_branding.name,
        "alt_text_en": service.email_branding.alt_text_en,
        "alt_text_fr": service.email_branding.alt_text_fr,
    }


def inactive_service_failure(notification):
    notification.status = NOTIFICATION_TECHNICAL_FAILURE
    dao_update_notification(notification)
    raise NotificationTechnicalFailureException(
        "Send {} for notification id {} to provider is not allowed: service {} is inactive".format(
            notification.notification_type, notification.id, notification.service_id
        )
    )


def empty_message_failure(notification):
    notification.status = NOTIFICATION_TECHNICAL_FAILURE
    dao_update_notification(notification)
    current_app.logger.error(
        "Send {} for notification id {} (service {}) is not allowed: empty message".format(
            notification.notification_type, notification.id, notification.service_id
        )
    )


def malware_failure(notification):
    notification.status = NOTIFICATION_VIRUS_SCAN_FAILED
    dao_update_notification(notification)
    raise MalwareDetectedException(
        "Send {} for notification id {} to provider is not allowed. Notification contains malware".format(
            notification.notification_type, notification.id
        )
    )


def document_download_internal_error(notification):
    notification.status = NOTIFICATION_TECHNICAL_FAILURE
    dao_update_notification(notification)
    current_app.logger.error(f"Cannot send notification {notification.id}, document-download-api internal error.")
    raise DocumentDownloadException


def contains_pii(notification, text_content):
    for sin in re.findall(r"\s\d{3}-\d{3}-\d{3}\s", text_content):
        if luhn(sin.replace("-", "").strip()):
            fail_pii(notification, "Social Insurance Number")
            return


def fail_pii(notification, pii_type):
    notification.status = NOTIFICATION_CONTAINS_PII
    dao_update_notification(notification)
    raise NotificationTechnicalFailureException(
        "Send {} for notification id {} to provider is not allowed. Notification contains PII: {}".format(
            notification.notification_type, notification.id, pii_type
        )
    )


def luhn(n):
    r = [int(ch) for ch in n][::-1]
    return (sum(r[0::2]) + sum(sum(divmod(d * 2, 10)) for d in r[1::2])) % 10 == 0
