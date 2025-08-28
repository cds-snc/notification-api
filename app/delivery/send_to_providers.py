from datetime import datetime

from flask import current_app

from notifications_utils.recipients import ValidatedPhoneNumber, validate_and_format_email_address
from notifications_utils.template import HTMLEmailTemplate, PlainTextEmailTemplate, SMSMessageTemplate
from notifications_utils.template2 import (
    make_substitutions,
    make_substitutions_in_subject,
    render_html_email,
    render_notify_markdown,
)

from app import attachment_store, clients, statsd_client, provider_service
from app.attachments.types import UploadedAttachmentMetadata
from app.celery.research_mode_tasks import send_sms_response, send_email_response
from app.clients import Client
from app.constants import (
    EMAIL_TYPE,
    INTERNAL_PROCESSING_LIMIT,
    KEY_TYPE_TEST,
    NOTIFICATION_VIRUS_SCAN_FAILED,
    NOTIFICATION_SENDING,
    SMS_TYPE,
)
from app.dao.notifications_dao import dao_update_notification
from app.dao.templates_dao import dao_get_template_by_id
from app.exceptions import InactiveServiceException, NotificationTechnicalFailureException
from app.feature_flags import is_feature_enabled, FeatureFlag
from app.models import Notification
from app.service.utils import compute_source_email_address
from app.utils import create_uuid, get_html_email_options


def send_sms_to_provider(
    notification: Notification,
    sms_sender_id=None,
) -> None:
    """
    Send an HTTP request to an SMS backend provider to initiate an SMS message to a veteran.  Do not attempt to
    switch providers if one fails.

    When the backend provider has sms_sender_specifics, use messaging_service_sid, if available, for the sender's
    identity instead of the sender's phone number.
    """

    service = notification.service

    if not service.active:
        # always raises NotificationTechnicalFailureException
        inactive_service_failure(notification=notification)

    if notification.status != 'created':
        return

    # This is an instance of one of the classes defined in app/clients/.
    client = client_to_use(notification)
    if client is None:
        raise RuntimeError(f'Could not find a client for notification {notification.id}.')

    template_model = dao_get_template_by_id(notification.template_id, notification.template_version)

    template = SMSMessageTemplate(
        template_model.__dict__,
        values=notification.personalisation,
        prefix=service.name,
        show_prefix=service.prefix_sms,
    )

    if service.research_mode or notification.key_type == KEY_TYPE_TEST:
        notification.reference = create_uuid()
        update_notification_to_sending(notification, client)
        send_sms_response(client.get_name(), str(notification.id), notification.to, notification.reference)
    else:
        try:
            # Send a SMS message using the "to" attribute to specify the recipient.
            reference = client.send_sms(
                to=ValidatedPhoneNumber(notification.to).formatted,
                content=str(template),
                reference=str(notification.id),
                sender=notification.reply_to_text,
                service_id=notification.service_id,
                sms_sender_id=sms_sender_id,
                created_at=notification.created_at,
            )
        except Exception:
            notification.billable_units = template.fragment_count
            dao_update_notification(notification)
            raise

        notification.billable_units = template.fragment_count
        notification.reference = reference
        update_notification_to_sending(notification, client)
        current_app.logger.info(f'Saved provider reference: {reference} for notification id: {notification.id}')

    delta_milliseconds = (datetime.utcnow() - notification.created_at).total_seconds() * 1000
    statsd_client.timing('sms.total-time', delta_milliseconds)


def send_email_to_provider(notification: Notification):
    # This is a relationship to a Service instance.
    service = notification.service

    if not service.active:
        # This raises an exception.
        inactive_service_failure(notification=notification)

    if notification.status != 'created':
        raise RuntimeError(f'Duplication prevention - notification.status = {notification.status}')

    client = client_to_use(notification)

    # TODO: #883 remove that code or extract attachment handling to separate method
    # Extract any file objects from the personalization
    file_keys = [k for k, v in (notification.personalisation or {}).items() if isinstance(v, dict) and 'file_name' in v]
    attachments = []

    personalisation_data = notification.personalisation.copy()

    for key in file_keys:
        uploaded_attachment_metadata: UploadedAttachmentMetadata = personalisation_data[key]
        if uploaded_attachment_metadata['sending_method'] == 'attach':
            file_data = attachment_store.get(
                service_id=service.id,
                attachment_id=uploaded_attachment_metadata['id'],
                decryption_key=uploaded_attachment_metadata['encryption_key'],
                sending_method=uploaded_attachment_metadata['sending_method'],
            )
            attachments.append({'name': uploaded_attachment_metadata['file_name'], 'data': file_data})
            del personalisation_data[key]
        else:
            personalisation_data[key] = personalisation_data[key]['url']

    if is_feature_enabled(FeatureFlag.REVISED_TEMPLATE_RENDERING):
        html, plain_text, subject = _get_email_content(notification, personalisation_data)
    else:
        html, plain_text, subject = _get_email_content_legacy(notification, personalisation_data)

    if service.research_mode or notification.key_type == KEY_TYPE_TEST:
        notification.reference = create_uuid()
        update_notification_to_sending(notification, client)
        send_email_response(notification.reference, notification.to)
    else:
        email_reply_to = notification.reply_to_text

        # Log how long it spent in our system before we sent it
        total_time = (datetime.utcnow() - notification.created_at).total_seconds()
        if total_time >= INTERNAL_PROCESSING_LIMIT:
            current_app.logger.warning(
                'Exceeded maximum total time (%s) to send %s notification: %s seconds',
                INTERNAL_PROCESSING_LIMIT,
                EMAIL_TYPE,
                total_time,
            )
        else:
            current_app.logger.info(
                'Total time spent to send %s notification: %s seconds',
                EMAIL_TYPE,
                total_time,
            )
        reference = client.send_email(
            source=compute_source_email_address(service, client),
            to_addresses=validate_and_format_email_address(notification.to),
            subject=subject,
            body=plain_text,
            html_body=html,
            reply_to_address=validate_and_format_email_address(email_reply_to) if email_reply_to else None,
            attachments=attachments,
        )
        notification.reference = reference
        update_notification_to_sending(notification, client)
        current_app.logger.info('Saved provider reference: %s for notification id: %s', reference, notification.id)

    delta_milliseconds = (datetime.utcnow() - notification.created_at).total_seconds() * 1000
    statsd_client.timing('email.total-time', delta_milliseconds)


def _get_email_content(notification: Notification, personalization: dict[str, str]) -> tuple[str, str, str]:
    """
    Return the HTML body, plain text body, and subject of an e-mail notification using the revised template rendering
    implementation.

    Calls to make_substitutions, make_substitutions_in_subject, and render_notify_markdown could raise TypeError or
    ValueError if there are missing personalization values.  However, exceptions are not caught here because upstream
    code should have validated that all required value are present.  An exception in this function indicates a
    programming error.
    """

    if notification.template.html:
        # The template, rendered as HTML, is stored in the database with placeholders intact.
        html = make_substitutions(notification.template.html, personalization, True)
    else:
        # Render the template, and make substitutions using personalizations, if any.
        html = render_notify_markdown(notification.template.content, personalization, True)

    options: dict = get_html_email_options(str(notification.id))

    # This function plugs the HTML content body into a Jinja2 template that includes branding and styling.
    html = render_html_email(html, None, options.get('ga4_open_email_event_url'))

    if notification.template.plain_text:
        # The template, rendered as plain text, is stored in the database with placeholders intact.
        plain_text = make_substitutions(notification.template.plain_text, personalization, False)
    else:
        # Render the template, and make substitutions using personalizations, if any.
        plain_text = render_notify_markdown(notification.template.content, personalization, False)

    subject = make_substitutions_in_subject(notification.template.subject, personalization)

    return html, plain_text, subject


def _get_email_content_legacy(notification: Notification, personalization: dict[str, str]) -> tuple[str, str, str]:
    """
    Return the HTML body, plain text body, and subject of an e-mail notification using the legacy template rendering
    implementation.  The legacy implementation does not support pre-rendering and caching templates because it requires
    making personalization substitutions before converting the markdown.
    """

    template_dict = dao_get_template_by_id(notification.template_id, notification.template_version).__dict__

    html = str(
        HTMLEmailTemplate(
            template_dict,
            personalization,
            **get_html_email_options(str(notification.id)),
        )
    )

    utils_template = PlainTextEmailTemplate(template_dict, personalization)
    return html, str(utils_template), utils_template.subject


def update_notification_to_sending(
    notification,
    client,
):
    notification.sent_at = datetime.utcnow()
    notification.sent_by = client.get_name()
    notification.status = NOTIFICATION_SENDING
    dao_update_notification(notification)


def client_to_use(notification: Notification) -> Client | None:
    """Return a subclass of Client to process a notification.

    Args:
        notification (Notification): A Notification instance.

    Returns:
        Client: A subclass of Client.

    Raises:
        RuntimeError: If no active providers are available.
        ValueError: If no client is available.
    """

    try:
        provider = provider_service.get_provider(notification)
        return clients.get_client_by_name_and_type(provider.identifier, notification.notification_type)
    except ValueError:
        current_app.logger.exception("Couldn't retrieve a client for the given provider.")
        raise


def get_provider_id(notification: Notification) -> str:
    # the provider from template has highest priority, so if it is valid we'll use that one
    providers = [
        notification.template.provider_id,
        {EMAIL_TYPE: notification.service.email_provider_id, SMS_TYPE: notification.service.sms_provider_id}[
            notification.notification_type
        ],
    ]

    return next((provider for provider in providers if provider is not None), None)


def inactive_service_failure(notification: Notification):
    """Called when the service is inactive to raise InactiveServiceException with the proper error message.

    Raises:
        InactiveServiceException: always
    """
    raise InactiveServiceException(
        f'Send {notification.notification_type} to provider is not allowed. '
        f'Service {notification.service_id} is inactive. Notification {notification.id}'
    )


def malware_failure(notification):
    notification.status = NOTIFICATION_VIRUS_SCAN_FAILED
    dao_update_notification(notification)
    raise NotificationTechnicalFailureException(
        'Send {} for notification id {} to provider is not allowed. Notification contains malware'.format(
            notification.notification_type, notification.id
        )
    )
