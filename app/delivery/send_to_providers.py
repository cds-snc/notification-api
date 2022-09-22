import re
from datetime import datetime

import app.googleanalytics.pixels as gapixels
from flask import current_app
from notifications_utils.recipients import (
    validate_and_format_phone_number,
    validate_and_format_email_address
)
from notifications_utils.template import HTMLEmailTemplate, PlainTextEmailTemplate, SMSMessageTemplate

from app import attachment_store
from app import clients, statsd_client, create_uuid, provider_service
from app.attachments.types import UploadedAttachmentMetadata
from app.celery.research_mode_tasks import send_sms_response, send_email_response
from app.dao.notifications_dao import (
    dao_update_notification
)
from app.dao.provider_details_dao import (
    get_provider_details_by_notification_type,
    dao_toggle_sms_provider, get_provider_details_by_id
)
from app.dao.templates_dao import dao_get_template_by_id
from app.exceptions import NotificationTechnicalFailureException, InvalidProviderException
from app.feature_flags import (
    is_provider_enabled,
    is_gapixel_enabled,
    is_feature_enabled,
    FeatureFlag
)
from app.models import (
    SMS_TYPE,
    KEY_TYPE_TEST,
    BRANDING_BOTH,
    BRANDING_ORG_BANNER,
    EMAIL_TYPE,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_VIRUS_SCAN_FAILED,
    NOTIFICATION_CONTAINS_PII,
    NOTIFICATION_SENDING,
    Notification, ProviderDetails
)
from app.service.utils import compute_source_email_address


def send_sms_to_provider(notification, sms_sender_id=None):
    """
    Send an HTTP request to an SMS backend provider to initiate an SMS message to a veteran.

    When the backend provider has sms_sender_specifics, use messaging_service_sid, if available, for the sender's
    identity instead of the sender's phone number.
    """

    service = notification.service

    if not service.active:
        # always raises NotificationTechnicalFailureException
        technical_failure(notification=notification)

    if notification.status != "created":
        return

    # This is an instance of one of the classes defined in app/clients/.
    provider = provider_to_use(notification)

    template_model = dao_get_template_by_id(notification.template_id, notification.template_version)

    template = SMSMessageTemplate(
        template_model.__dict__,
        values=notification.personalisation,
        prefix=service.name,
        show_prefix=service.prefix_sms,
    )

    if service.research_mode or notification.key_type == KEY_TYPE_TEST:
        notification.reference = create_uuid()
        update_notification_to_sending(notification, provider)
        send_sms_response(provider.get_name(), str(notification.id), notification.to, notification.reference)

    else:
        try:
            # Send a SMS message using the "to" attribute to specify the recipient.
            reference = provider.send_sms(
                to=validate_and_format_phone_number(notification.to, international=notification.international),
                content=str(template),
                reference=str(notification.id),
                sender=notification.reply_to_text,
                service_id=notification.service_id,
                sms_sender_id=sms_sender_id,
            )
        except Exception as e:
            notification.billable_units = template.fragment_count
            dao_update_notification(notification)
            dao_toggle_sms_provider(provider.name)
            raise e

        notification.billable_units = template.fragment_count
        notification.reference = reference
        update_notification_to_sending(notification, provider)
        current_app.logger.info(f"Saved provider reference: {reference} for notification id: {notification.id}")

    delta_milliseconds = (datetime.utcnow() - notification.created_at).total_seconds() * 1000
    statsd_client.timing("sms.total-time", delta_milliseconds)


def send_email_to_provider(notification):
    service = notification.service
    if not service.active:
        technical_failure(notification=notification)
        return

    # TODO: no else - replace with if statement raising error / logging when not 'created'
    if notification.status == 'created':
        provider = provider_to_use(notification)

        # TODO: remove that code or extract attachment handling to separate method
        # Extract any file objects from the personalization
        file_keys = [
            k for k, v in (notification.personalisation or {}).items() if isinstance(v, dict) and 'file_name' in v
        ]
        attachments = []

        personalisation_data = notification.personalisation.copy()

        for key in file_keys:
            uploaded_attachment_metadata: UploadedAttachmentMetadata = personalisation_data[key]
            if uploaded_attachment_metadata['sending_method'] == 'attach':
                file_data = attachment_store.get(
                    service_id=service.id,
                    attachment_id=uploaded_attachment_metadata['id'],
                    decryption_key=uploaded_attachment_metadata['encryption_key'],
                    sending_method=uploaded_attachment_metadata['sending_method']
                )
                attachments.append({
                    "name": uploaded_attachment_metadata['file_name'],
                    "data": file_data
                })
                del personalisation_data[key]
            else:
                personalisation_data[key] = personalisation_data[key]['url']

        template_dict = dao_get_template_by_id(notification.template_id, notification.template_version).__dict__

        html_email = HTMLEmailTemplate(
            template_dict,
            values=personalisation_data,
            **get_html_email_options(notification, provider)
        )

        plain_text_email = PlainTextEmailTemplate(
            template_dict,
            values=personalisation_data
        )

        if current_app.config["SCAN_FOR_PII"]:
            contains_pii(notification, str(plain_text_email))

        if service.research_mode or notification.key_type == KEY_TYPE_TEST:
            notification.reference = str(create_uuid())
            update_notification_to_sending(notification, provider)
            send_email_response(notification.reference, notification.to)
        else:
            email_reply_to = notification.reply_to_text

            reference = provider.send_email(
                source=compute_source_email_address(service, provider),
                to_addresses=validate_and_format_email_address(notification.to),
                subject=plain_text_email.subject,
                body=str(plain_text_email),
                html_body=str(html_email),
                reply_to_address=validate_and_format_email_address(email_reply_to) if email_reply_to else None,
                attachments=attachments
            )
            notification.reference = reference
            update_notification_to_sending(notification, provider)
            current_app.logger.info(f"Saved provider reference: {reference} for notification id: {notification.id}")

        delta_milliseconds = (datetime.utcnow() - notification.created_at).total_seconds() * 1000
        statsd_client.timing("email.total-time", delta_milliseconds)


def update_notification_to_sending(notification, provider):
    notification.sent_at = datetime.utcnow()
    notification.sent_by = provider.get_name()
    notification.status = NOTIFICATION_SENDING
    dao_update_notification(notification)


# TODO: remove this when provider strategy implemented
def should_use_provider(provider):
    return provider.active and is_provider_enabled(current_app, provider.identifier)


def load_provider(provider_id: str) -> ProviderDetails:
    provider_details = get_provider_details_by_id(provider_id)
    if provider_details is None:
        raise InvalidProviderException(f'provider {provider_id} could not be found')
    elif not provider_details.active:
        raise InvalidProviderException(f'provider {provider_id} is not active')
    else:
        return provider_details


def provider_to_use(notification: Notification):

    if is_feature_enabled(FeatureFlag.PROVIDER_STRATEGIES_ENABLED):
        provider = provider_service.get_provider(notification)
        return clients.get_client_by_name_and_type(provider.identifier, notification.notification_type)

    if is_feature_enabled(FeatureFlag.TEMPLATE_SERVICE_PROVIDERS_ENABLED):
        provider_id = get_provider_id(notification)

        if provider_id:
            return clients.get_client_by_name_and_type(
                load_provider(provider_id).identifier,
                notification.notification_type
            )

    # This is a list of ProviderDetails instances sorted by their "priority" attribute.
    active_providers_in_order = [
        p for p in get_provider_details_by_notification_type(notification.notification_type, notification.international)
        if should_use_provider(p)
    ]

    if not active_providers_in_order:
        current_app.logger.error(
            f"{notification.notification_type} {notification.id} failed as no active providers"
        )
        raise Exception(f"No active {notification.notification_type} providers")

    # This returns an instance of one of the classes defined in app/clients/.
    return clients.get_client_by_name_and_type(active_providers_in_order[0].identifier, notification.notification_type)


def get_provider_id(notification: Notification) -> str:
    # the provider from template has highest priority, so if it is valid we'll use that one
    providers = [
        notification.template.provider_id,
        {
            EMAIL_TYPE: notification.service.email_provider_id,
            SMS_TYPE: notification.service.sms_provider_id
        }[notification.notification_type]
    ]

    return next((provider for provider in providers if provider is not None), None)


def get_logo_url(base_url, logo_file):
    bucket = current_app.config['ASSET_UPLOAD_BUCKET_NAME']
    domain = current_app.config['ASSET_DOMAIN']
    return "https://{}.{}/{}".format(bucket, domain, logo_file)


def get_html_email_options(notification, provider):
    options_dict = {}
    if is_gapixel_enabled(current_app):
        options_dict['ga_pixel_url'] = gapixels.build_ga_pixel_url(notification, provider)

    service = notification.service
    if service.email_branding is None:
        options_dict.update(
            {
                'default_banner': True,
                'brand_banner': False
            }
        )
    else:
        logo_url = get_logo_url(
            current_app.config['ADMIN_BASE_URL'],
            service.email_branding.logo
        ) if service.email_branding.logo else None

        options_dict.update(
            {
                'default_banner': service.email_branding.brand_type == BRANDING_BOTH,
                'brand_banner': service.email_branding.brand_type == BRANDING_ORG_BANNER,
                'brand_colour': service.email_branding.colour,
                'brand_logo': logo_url,
                'brand_text': service.email_branding.text,
                'brand_name': service.email_branding.name
            }
        )

    return options_dict


def technical_failure(notification):
    notification.status = NOTIFICATION_TECHNICAL_FAILURE
    dao_update_notification(notification)
    raise NotificationTechnicalFailureException(
        "Send {} for notification id {} to provider is not allowed: service {} is inactive".format(
            notification.notification_type,
            notification.id,
            notification.service_id))


def malware_failure(notification):
    notification.status = NOTIFICATION_VIRUS_SCAN_FAILED
    dao_update_notification(notification)
    raise NotificationTechnicalFailureException(
        "Send {} for notification id {} to provider is not allowed. Notification contains malware".format(
            notification.notification_type,
            notification.id))


def contains_pii(notification, text_content):
    for sin in re.findall(r'\s\d{3}-\d{3}-\d{3}\s', text_content):
        if luhn(sin.replace("-", "").strip()):
            fail_pii(notification, "Social Insurance Number")
            return


def fail_pii(notification, pii_type):
    notification.status = NOTIFICATION_CONTAINS_PII
    dao_update_notification(notification)
    raise NotificationTechnicalFailureException(
        "Send {} for notification id {} to provider is not allowed. Notification contains PII: {}".format(
            notification.notification_type,
            notification.id,
            pii_type))


def luhn(n):
    r = [int(ch) for ch in n][::-1]
    return (sum(r[0::2]) + sum(sum(divmod(d * 2, 10)) for d in r[1::2])) % 10 == 0
