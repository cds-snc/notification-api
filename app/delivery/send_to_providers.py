import base64
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
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

from app import (
    bounce_rate_client,
    clients,
    create_uuid,
    document_download_client,
    redis_store,
    statsd_client,
)
from app.celery.research_mode_tasks import send_email_response, send_sms_response
from app.clients.sms import SmsSendingVehicles
from app.config import Config
from app.dao.files_dao import dao_get_ready_files_by_template_id
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
    PinpointConflictException,
    PinpointValidationException,
)
from app.models import (
    BRANDING_BOTH_EN,
    BRANDING_BOTH_FR,
    BRANDING_ORG_BANNER_NEW,
    EMAIL_TYPE,
    KEY_TYPE_TEST,
    NOTIFICATION_CONTAINS_PII,
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


def _get_template_files_from_cache_or_db(job_id: Optional[UUID], template_id: UUID) -> List[Dict[str, Any]]:
    """
    Fetch template file attachments from cache (for bulk sends) or from DB.

    For bulk sends (job_id is set): Retrieves from Redis cache (pre-cached by process_job).
    For one-off sends (no job_id): Fetches from DB directly.

    Returns a list of attachment dicts: [{"name": str, "document_id": UUID, "mime_type": str, "service_id": UUID}, ...]
    """
    # Try to get from cache if this is a bulk send
    if job_id:
        cache_key = f"template_files:{job_id}"
        try:
            cached = redis_store.get(cache_key)
            if cached:
                current_app.logger.info(f"Retrieved template files from Redis cache for job {job_id}")
                return json.loads(cached)
        except Exception as e:
            current_app.logger.warning(f"Failed to retrieve template files from cache for job {job_id}: {e}")

    # Fetch from database (for one-off sends or cache miss)
    ready_files = dao_get_ready_files_by_template_id(template_id)
    file_metadata = []

    for file in ready_files:
        file_metadata.append(
            {
                "name": file.name,
                "document_id": str(file.document_id),
                "mime_type": file.mime_type,
                "service_id": str(file.service_id),
                "file_id": str(file.id),
                "file_size": file.file_size,
            }
        )

    # Cache on miss for bulk sends (safety measure if job_id cache expires or fails)
    # Even cache empty list to prevent repeated DB queries for templates with no attachments
    if job_id:
        cache_key = f"template_files:{job_id}"
        try:
            redis_store.set(cache_key, json.dumps(file_metadata), ex=86400)
            current_app.logger.info(f"Cached {len(file_metadata)} template files for job {job_id} on retrieval miss")
        except Exception as e:
            current_app.logger.warning(f"Failed to cache template files for job {job_id}: {e}")

    return file_metadata


def _download_template_file(
    service_id: UUID, document_id: str, filename: str, mime_type: Optional[str]
) -> Optional[Dict[str, Any]]:
    """
    Download a template file from document-download-api.

    Files are only included if they have status='uploaded', meaning they have already
    passed the malware scan, so no additional scan check is needed.

    Returns: {"name": str, "data": bytes, "mime_type": str} or None if download fails
    """
    try:
        current_app.logger.info(f"Downloading template file: document_id={document_id}, service_id={service_id}")
        # Construct download URL with query parameter
        url = f"{current_app.config.get('DOCUMENT_DOWNLOAD_API_HOST')}/services/{service_id}/documents/{document_id}?sending_method=template_attach"
        auth_header = f"Bearer {current_app.config.get('DOCUMENT_DOWNLOAD_API_KEY')}"
        retries = Retry(total=5)
        http = PoolManager(retries=retries)
        response = http.request(
            "GET",
            url=url,
            headers={"Authorization": auth_header},
        )

        if response.status != 200:
            current_app.logger.error(f"Failed to download template file {document_id}: HTTP {response.status}")
            return None

        return {
            "name": filename,
            "data": response.data,
            "mime_type": mime_type or "application/octet-stream",
        }

    except Exception as e:
        current_app.logger.error(f"Could not download template file {document_id}: {e}")
        return None


def _get_template_attachments(notification: Notification) -> List[Dict[str, Any]]:
    """
    Fetch and download template file attachments for a notification.

    Returns list of attachment dicts: [{"name": str, "data": bytes, "mime_type": str}, ...]
    """
    template_attachments = []

    # Get file metadata from cache or DB
    file_metadata = _get_template_files_from_cache_or_db(notification.job_id, notification.template_id)

    if not file_metadata:
        return []

    service_id = notification.service.id

    for file_info in file_metadata:
        attachment = _download_template_file(
            service_id,
            file_info["document_id"],
            file_info["name"],
            file_info["mime_type"],
        )
        if attachment:
            template_attachments.append(attachment)
        else:
            current_app.logger.warning(f"Skipping template file {file_info['file_id']} for notification {notification.id}")

    return template_attachments


def _persist_template_attachment_metadata(notification: Notification) -> None:
    """
    Write template file attachment metadata into notification.personalisation
    so it is available for the notification history page.

    For one-off sends, the admin pre-populates _file_N keys before calling the API.
    For bulk sends, this data is missing because the CSV personalisation only contains
    user-provided columns. This function fills that gap by reading the same file metadata
    used to download attachments and writing it into the personalisation record.

    Only writes if _file_0 is not already present (avoids overwriting one-off send data).
    """
    personalisation = notification.personalisation or {}

    # If admin already populated template attachment personalisation, skip
    if "_file_0" in personalisation:
        return

    file_metadata = _get_template_files_from_cache_or_db(notification.job_id, notification.template_id)
    if not file_metadata:
        return

    updated_personalisation = personalisation.copy()
    for index, file_info in enumerate(file_metadata):
        updated_personalisation[f"_file_{index}"] = {
            "document": {
                "id": file_info["document_id"],
                "filename": file_info["name"],
                "mime_type": file_info["mime_type"],
                "file_size": file_info.get("file_size"),
                "sending_method": "template_attach",
            }
        }

    notification.personalisation = updated_personalisation


def send_sms_to_provider(notification):
    service = notification.service

    if not service.active:
        inactive_service_failure(notification=notification)
        return

    formatted_recipient = validate_and_format_phone_number(notification.to, international=notification.international)
    sending_to_internal_test_number = formatted_recipient == current_app.config["INTERNAL_TEST_NUMBER"]
    sending_to_dryrun_number = formatted_recipient == current_app.config["EXTERNAL_TEST_NUMBER"]

    # Only process notifications with status 'created' to guarantee idempotency of this
    # function. If the status is not 'created', it means the notification has already
    # been processed and sent to a provider, so we should not attempt to send it again.
    if notification.status != "created":
        return

    provider = provider_to_use(
        SMS_TYPE,
        notification.id,
        notification.to,
        notification.international,
        notification.reply_to_text,
        template_id=notification.template_id,
    )

    template_obj = dao_get_template_by_id(notification.template_id, notification.template_version)
    template_dict = template_obj.__dict__
    template_dict["process_type"] = template_obj.process_type

    template = SMSMessageTemplate(
        template_dict,
        values=notification.personalisation,
        prefix=service.name,
        show_prefix=service.prefix_sms,
    )

    if is_blank(template):
        empty_message_failure(notification=notification)
        return

    if service.research_mode or notification.key_type == KEY_TYPE_TEST or sending_to_internal_test_number:
        current_app.logger.info(f"notification {notification.id} is sending to INTERNAL_TEST_NUMBER, no boto call to AWS.")
        notification.reference = str(create_uuid())
        update_notification_to_sending(notification, provider)
        send_sms_response(provider.get_name(), notification.to, notification.reference)
    else:
        try:
            template_category_id = template_dict.get("template_category_id")
            if template_category_id is not None:
                sending_vehicle = SmsSendingVehicles(dao_get_template_category_by_id(template_category_id).sms_sending_vehicle)
            else:
                sending_vehicle = None
            reference = provider.send_sms(
                to=formatted_recipient,
                content=str(template),
                reference=str(notification.id),
                sender=notification.reply_to_text,
                template_id=notification.template_id,
                service_id=notification.service_id,
                sending_vehicle=sending_vehicle,
            )
        except (PinpointConflictException, PinpointValidationException) as e:
            raise e
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
                if sending_to_dryrun_number:
                    send_sms_response(provider.get_name(), notification.to, reference)
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
    # 422 "Scan failure" response is sent if the document cannot be scanned
    elif document_download_response_code == 422:
        current_app.logger.error(f"Malware scan failed for notification.id: {notification.id}, send anyway")
        return
    # 408 "Request Timeout" response is sent if the scan is not complete before it times out
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


def _get_unsubscribe_headers(unsubscribe_link):
    """Returns RFC 8058 one-click unsubscribe headers if a link is present."""
    if unsubscribe_link:
        return {
            "List-Unsubscribe": f"<{unsubscribe_link}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    return {}


def _validate_unsubscribe_url(url, notification_id):
    """Validates that the unsubscribe URL is a well-formed https URL with a proper hostname.
    Reuses the same criteria as the existing https_url JSON Schema definition in the project
    (scheme must be https, host must look like a real domain with at least one dot).
    Also rejects URLs containing control characters (CR, LF, etc.) to prevent header injection,
    since this value is placed directly into an email header.
    Returns the URL if valid, None otherwise.
    """
    if not url:
        return None
    try:
        # Reject any control characters before further parsing — they can enable header injection
        # when the URL is interpolated into a List-Unsubscribe header value.
        if any(c < "\x20" for c in url):
            raise ValueError("URL contains control characters")
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError("scheme must be https")
        if not parsed.hostname or "." not in parsed.hostname:
            raise ValueError("hostname must be a valid domain")
    except Exception:
        current_app.logger.warning(
            f"Notification {notification_id} has an invalid unsubscribe_url "
            f"(must be a valid https URL with a proper domain): {url!r}. Header will not be added."
        )
        return None
    return url


def send_email_to_provider(notification: Notification):
    current_app.logger.info(f"Sending email to provider for notification id {notification.id}")
    service = notification.service
    if not service.active:
        inactive_service_failure(notification=notification)
        return

    # Only process notifications with status 'created' to guarantee idempotency of this
    # function. If the status is not 'created', it means the notification has already
    # been processed and sent to a provider, so we should not attempt to send it again.
    if notification.status != "created":
        return

    provider = provider_to_use(EMAIL_TYPE, notification.id)

    # Extract any file objects from the personalization (but exclude template attachments)
    file_keys = [
        k
        for k, v in (notification.personalisation or {}).items()
        if isinstance(v, dict) and "document" in v and v["document"].get("sending_method") != "template_attach"
    ]
    attachments = []

    personalisation_data = notification.personalisation.copy()

    for key in file_keys:
        check_file_url(personalisation_data[key]["document"], notification.id)
        sending_method = personalisation_data[key]["document"].get("sending_method")
        direct_file_url = personalisation_data[key]["document"]["direct_file_url"]
        filename = personalisation_data[key]["document"].get("filename")
        mime_type = personalisation_data[key]["document"].get("mime_type")
        document_id = personalisation_data[key]["document"]["id"]
        current_app.logger.info(
            f"Calling document_download_client.check_scan_verdict() for document_id: {document_id} and notification_id: {notification.id}"
        )
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

    # Fetch and merge template file attachments
    template_attachments = _get_template_attachments(notification)
    attachments = attachments + template_attachments

    # Persist template attachment metadata into notification.personalisation so that
    # the notification history page can display them later (bulk sends don't have
    # this info pre-populated by the admin like one-off sends do).
    if template_attachments:
        _persist_template_attachment_metadata(notification)

    template_obj = dao_get_template_by_id(notification.template_id, notification.template_version)
    template_dict = template_obj.__dict__
    template_dict["process_type"] = template_obj.process_type

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

    # Service-managed one-click unsubscribe: if the template has use_custom_unsubscribe_url
    # enabled and the personalisation contains ((unsubscribe_url)), ((unsub_url)), or ((unsub_link)),
    # use that URL for the RFC 8058 List-Unsubscribe header only (no Notify-hosted page or body link).
    unsubscribe_link_for_header = None
    if getattr(template_obj, "use_custom_unsubscribe_url", False) and personalisation_data:
        raw_url = (
            personalisation_data.get("unsubscribe_url")
            or personalisation_data.get("unsub_url")
            or personalisation_data.get("unsub_link")
        )
        unsubscribe_link_for_header = _validate_unsubscribe_url(raw_url, notification.id)

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

        from_address = get_from_address(friendly_from=service.name, email_from=service.email_from, sending_domain=sending_domain)
        email_reply_to = notification.reply_to_text

        reference = provider.send_email(
            from_address,
            validate_and_format_email_address(notification.to),
            plain_text_email.subject,
            body=str(plain_text_email),
            html_body=str(html_email),
            reply_to_address=validate_and_format_email_address(email_reply_to) if email_reply_to else None,
            attachments=attachments,
            extra_headers=_get_unsubscribe_headers(unsubscribe_link_for_header),
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
    notification.status = NOTIFICATION_TECHNICAL_FAILURE
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

    cannot_determine_recipient_country = False
    recipient_outside_canada = False
    if to is not None:
        match = next(iter(phonenumbers.PhoneNumberMatcher(to, "US")), None)
        if match is None:
            cannot_determine_recipient_country = True
        elif phonenumbers.region_code_for_number(match.number) not in ["CA", "US"]:
            recipient_outside_canada = True
    using_sc_pool_template = template_id is not None and str(template_id) in current_app.config["AWS_PINPOINT_SC_TEMPLATE_IDS"]
    zone_1_outside_canada = recipient_outside_canada and not international
    do_not_use_pinpoint = (
        cannot_determine_recipient_country
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
