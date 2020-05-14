from datetime import datetime
import os
import urllib.request
import magic
import re

from flask import current_app
from notifications_utils.recipients import (
    validate_and_format_phone_number,
    validate_and_format_email_address
)
from notifications_utils.template import HTMLEmailTemplate, PlainTextEmailTemplate, SMSMessageTemplate

from app import clients, statsd_client, create_uuid
from app.dao.notifications_dao import (
    dao_update_notification
)
from app.dao.provider_details_dao import (
    get_provider_details_by_notification_type,
    dao_toggle_sms_provider
)
from app.celery.research_mode_tasks import send_sms_response, send_email_response
from app.dao.templates_dao import dao_get_template_by_id
from app.exceptions import NotificationTechnicalFailureException, MalwarePendingException
from app.models import (
    SMS_TYPE,
    KEY_TYPE_TEST,
    BRANDING_BOTH_EN,
    BRANDING_BOTH_FR,
    BRANDING_ORG_BANNER_NEW,
    EMAIL_TYPE,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_VIRUS_SCAN_FAILED,
    NOTIFICATION_CONTAINS_PII,
    NOTIFICATION_SENT,
    NOTIFICATION_SENDING
)
from app.clients.mlwr.mlwr import check_mlwr_score


def send_sms_to_provider(notification):
    service = notification.service

    if not service.active:
        technical_failure(notification=notification)
        return

    if notification.status == 'created':
        provider = provider_to_use(
            SMS_TYPE,
            notification.id,
            notification.international,
            notification.reply_to_text
        )

        template_model = dao_get_template_by_id(notification.template_id, notification.template_version)

        template = SMSMessageTemplate(
            template_model.__dict__,
            values=notification.personalisation,
            prefix=service.name,
            show_prefix=service.prefix_sms,
        )

        if service.research_mode or notification.key_type == KEY_TYPE_TEST:
            update_notification_to_sending(notification, provider)
            send_sms_response(provider.get_name(), str(notification.id), notification.to)

        else:
            try:
                provider.send_sms(
                    to=validate_and_format_phone_number(notification.to, international=notification.international),
                    content=str(template),
                    reference=str(notification.id),
                    sender=notification.reply_to_text
                )
            except Exception as e:
                notification.billable_units = template.fragment_count
                dao_update_notification(notification)
                dao_toggle_sms_provider(provider.name)
                raise e
            else:
                notification.billable_units = template.fragment_count
                update_notification_to_sending(notification, provider)

        delta_milliseconds = (datetime.utcnow() - notification.created_at).total_seconds() * 1000
        statsd_client.timing("sms.total-time", delta_milliseconds)


def send_email_to_provider(notification):
    service = notification.service
    if not service.active:
        technical_failure(notification=notification)
        return
    if notification.status == 'created':
        provider = provider_to_use(EMAIL_TYPE, notification.id)

        # Extract any file objects from the personalization
        file_keys = [
            k for k, v in (notification.personalisation or {}).items() if isinstance(v, dict) and 'document' in v
        ]
        attachments = []

        personalisation_data = notification.personalisation.copy()

        for key in file_keys:

            # Check if a MLWR sid exists
            if (current_app.config["MLWR_HOST"] and
                    'mlwr_sid' in personalisation_data[key]['document'] and
                    personalisation_data[key]['document']['mlwr_sid'] != "false"):

                mlwr_result = check_mlwr(personalisation_data[key]['document']['mlwr_sid'])

                if "state" in mlwr_result and mlwr_result["state"] == "completed":
                    # Update notification that it contains malware
                    if "submission" in mlwr_result and mlwr_result["submission"]['max_score'] >= 500:
                        malware_failure(notification=notification)
                        return
                else:
                    # Throw error so celery will retry in sixty seconds
                    raise MalwarePendingException

            try:
                req = urllib.request.Request(personalisation_data[key]['document']['direct_file_url'])
                with urllib.request.urlopen(req) as response:
                    buffer = response.read()
                    mime_type = magic.from_buffer(buffer, mime=True)
                    if mime_type == 'application/pdf':
                        attachments.append({"name": "{}.pdf".format(key), "data": buffer})
            except Exception:
                current_app.logger.error(
                    "Could not download and attach {}".format(personalisation_data[key]['document']['direct_file_url'])
                )

            personalisation_data[key] = personalisation_data[key]['document']['url']

        template_dict = dao_get_template_by_id(notification.template_id, notification.template_version).__dict__

        # Local Jinja support - Add USE_LOCAL_JINJA_TEMPLATES=True to .env
        # Add a folder to the project root called 'jinja_templates'
        # with a copy of 'email_template.jinja2' from notification-utils repo
        debug_template_path = (os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                               if os.environ.get('USE_LOCAL_JINJA_TEMPLATES') == 'True' else None)

        html_email = HTMLEmailTemplate(
            template_dict,
            values=personalisation_data,
            jinja_path=debug_template_path,
            **get_html_email_options(service)
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
            if service.sending_domain is None or service.sending_domain.strip() == "":
                sending_domain = current_app.config['NOTIFY_EMAIL_DOMAIN']
            else:
                sending_domain = service.sending_domain

            from_address = '"{}" <{}@{}>'.format(service.name, service.email_from,
                                                 sending_domain)

            email_reply_to = notification.reply_to_text

            reference = provider.send_email(
                from_address,
                validate_and_format_email_address(notification.to),
                plain_text_email.subject,
                body=str(plain_text_email),
                html_body=str(html_email),
                reply_to_address=validate_and_format_email_address(email_reply_to) if email_reply_to else None,
                attachments=attachments
            )
            notification.reference = reference
            update_notification_to_sending(notification, provider)

        delta_milliseconds = (datetime.utcnow() - notification.created_at).total_seconds() * 1000
        statsd_client.timing("email.total-time", delta_milliseconds)


def update_notification_to_sending(notification, provider):
    notification.sent_at = datetime.utcnow()
    notification.sent_by = provider.get_name()
    # We currently have no callback method for SNS
    # notification.status = NOTIFICATION_SENT if notification.international else NOTIFICATION_SENDING
    notification.status = NOTIFICATION_SENT if notification.notification_type == "sms" else NOTIFICATION_SENDING
    dao_update_notification(notification)


def provider_to_use(notification_type, notification_id, international=False, sender=None):
    active_providers_in_order = [
        p for p in get_provider_details_by_notification_type(notification_type, international) if p.active
    ]

    if not active_providers_in_order:
        current_app.logger.error(
            "{} {} failed as no active providers".format(notification_type, notification_id)
        )
        raise Exception("No active {} providers".format(notification_type))

    if sender is not None and notification_type == SMS_TYPE and sender[0] == "+":
        return clients.get_client_by_name_and_type("pinpoint", notification_type)

    return clients.get_client_by_name_and_type(active_providers_in_order[0].identifier, notification_type)


def get_logo_url(base_url, logo_file):
    bucket = current_app.config['ASSET_UPLOAD_BUCKET_NAME']
    domain = current_app.config['ASSET_DOMAIN']
    return "https://{}.{}/{}".format(bucket, domain, logo_file)


def get_html_email_options(service):
    if service.email_branding is None:
        if service.default_branding_is_french is True:
            return {
                'fip_banner_english': False,
                'fip_banner_french': True,
                'logo_with_background_colour': False,
            }
        else:
            return {
                'fip_banner_english': True,
                'fip_banner_french': False,
                'logo_with_background_colour': False,
            }

    logo_url = get_logo_url(
        current_app.config['ADMIN_BASE_URL'],
        service.email_branding.logo
    ) if service.email_branding.logo else None

    return {
        'fip_banner_english': service.email_branding.brand_type == BRANDING_BOTH_EN,
        'fip_banner_french': service.email_branding.brand_type == BRANDING_BOTH_FR,
        'logo_with_background_colour': service.email_branding.brand_type == BRANDING_ORG_BANNER_NEW,
        'brand_colour': service.email_branding.colour,
        'brand_logo': logo_url,
        'brand_text': service.email_branding.text,
        'brand_name': service.email_branding.name,
    }


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


def check_mlwr(sid):
    return check_mlwr_score(sid)


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
