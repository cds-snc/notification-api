import functools
import html
from datetime import datetime, timezone

import werkzeug
from flask import request, jsonify, current_app, abort
from notifications_utils.recipients import try_validate_and_format_phone_number

from app import api_user, authenticated_service, attachment_store
from app.va.identifier import IdentifierType
from app.feature_flags import is_feature_enabled, FeatureFlag
from app.pii import PiiIcn, PiiEdipi, PiiBirlsid, PiiPid, PiiVaProfileID
from app.attachments.mimetype import extract_and_validate_mimetype
from app.attachments.store import AttachmentStoreError
from app.attachments.types import UploadedAttachmentMetadata
from app.constants import (
    SCHEDULE_NOTIFICATIONS,
    SMS_TYPE,
    EMAIL_TYPE,
    LETTER_TYPE,
    UPLOAD_DOCUMENT,
)
from app.dao.service_sms_sender_dao import dao_get_default_service_sms_sender_by_service_id
from app.notifications.process_notifications import (
    persist_notification,
    persist_scheduled_notification,
    send_notification_to_queue,
    simulated_recipient,
    send_to_queue_for_recipient_info_based_on_recipient_identifier,
)
from app.notifications.validators import (
    validate_and_format_recipient,
    check_rate_limiting,
    validate_template,
    get_service_sms_sender_number,
)
from app.schema_validation import validate
from app.v2.errors import BadRequestError
from app.v2.notifications import v2_notification_blueprint
from app.v2.notifications.create_response import (
    create_post_sms_response_from_notification,
    create_post_email_response_from_notification,
    create_post_letter_response_from_notification,
)
from app.v2.notifications.notification_schemas import (
    post_sms_request,
    post_email_request,
    post_letter_request,
)
from app.utils import get_public_notify_type_text


def wrap_recipient_identifier_in_pii(form: dict):
    """Wrap the recipient identifier id_value in the appropriate PII class.

    This function takes a form containing recipient identifier data and wraps
    the id_value in the appropriate PII subclass based on the id_type. This provides
    encryption and controlled access to personally identifiable information.

    Args:
        form (dict): The validated form data containing recipient_identifier.
                     This dictionary may be modified in-place if a valid
                     recipient_identifier with id_type and id_value is present.

    Note:
        - The form parameter is modified in-place when PII wrapping occurs
        - Unknown id_types are logged as warnings but don't raise exceptions
        - PII instantiation errors are logged but don't prevent function completion
        - Only processes forms that contain recipient_identifier with both id_type and id_value
    """

    recipient_identifier = form.get('recipient_identifier')

    if not isinstance(recipient_identifier, dict):
        return

    # Get values with .get() to avoid KeyError
    id_type: str = recipient_identifier['id_type']
    id_value: str = recipient_identifier['id_value']

    # Map id_type to appropriate PII class
    pii_class_mapping: dict[str, type] = {
        IdentifierType.ICN.value: PiiIcn,
        IdentifierType.EDIPI.value: PiiEdipi,
        IdentifierType.BIRLSID.value: PiiBirlsid,
        IdentifierType.PID.value: PiiPid,
        IdentifierType.VA_PROFILE_ID.value: PiiVaProfileID,
    }

    pii_class: type | None = pii_class_mapping.get(id_type)

    if pii_class is not None:
        try:
            # Wrap the id_value in the appropriate PII class
            # Use False for is_encrypted since this is raw input data
            form['recipient_identifier']['id_value'] = pii_class(id_value, False)
            current_app.logger.debug(
                'Wrapped recipient identifier id_value in %s for id_type %s', pii_class.__name__, id_type
            )
        except Exception as e:
            current_app.logger.error(
                'Failed to wrap recipient identifier in PII class %s: %s', pii_class.__name__, str(e)
            )
            # Continue without wrapping if PII instantiation fails
    else:
        current_app.logger.warning('Unknown id_type %s - cannot wrap in PII class', id_type)


@v2_notification_blueprint.route('/<notification_type>', methods=['POST'])
def post_notification(notification_type):  # noqa: C901
    created_at = datetime.now(timezone.utc)
    try:
        request_json = request.get_json()
    except werkzeug.exceptions.BadRequest as e:
        raise BadRequestError(message=f'Error decoding arguments: {e.description}', status_code=400)

    if notification_type == EMAIL_TYPE:
        form = validate(request_json, post_email_request)
    elif notification_type == SMS_TYPE:
        form = validate(request_json, post_sms_request)

        if form.get('sms_sender_id') is None:
            # Use the service's default sms_sender.
            for sender in authenticated_service.service_sms_senders:
                if sender.is_default:
                    form['sms_sender_id'] = sender.id
                    break
            else:
                raise BadRequestError(
                    message='You must supply a value for sms_sender_id, or the service must have a default.'
                )
    elif notification_type == LETTER_TYPE:
        form = validate(request_json, post_letter_request)
    else:
        abort(404)

    if not authenticated_service.has_permissions(notification_type):
        raise BadRequestError(
            message='Service is not allowed to send {}'.format(
                get_public_notify_type_text(notification_type, plural=True)
            )
        )

    if is_feature_enabled(FeatureFlag.PII_ENABLED):
        # This might modify the form by converting form['recipient_identifier']['id_value'] to a Pii subclass.
        wrap_recipient_identifier_in_pii(form)

    scheduled_for = form.get('scheduled_for')

    if scheduled_for is not None:
        if not authenticated_service.has_permissions(SCHEDULE_NOTIFICATIONS):
            raise BadRequestError(message='Cannot schedule notifications (this feature is invite-only)')

    template, template_with_content = validate_template(
        form['template_id'],
        strip_keys_from_personalisation_if_send_attach(form.get('personalisation', {})),
        authenticated_service,
        notification_type,
    )

    check_rate_limiting(authenticated_service, api_user)

    reply_to = get_reply_to_text(notification_type, form, template)

    if notification_type == LETTER_TYPE:
        return jsonify(result='error', message='Not Implemented'), 501
    else:
        if 'email_address' in form or 'phone_number' in form:
            notification = process_sms_or_email_notification(
                form=form,
                notification_type=notification_type,
                api_key=api_user,
                template=template,
                service=authenticated_service,
                reply_to_text=reply_to,
                created_at=created_at,
            )
        else:
            # This execution path uses a given recipient identifier to lookup the
            # recipient's e-mail address or phone number.
            notification = process_notification_with_recipient_identifier(
                form=form,
                notification_type=notification_type,
                api_key=api_user,
                template=template,
                service=authenticated_service,
                reply_to_text=reply_to,
                created_at=created_at,
            )

        template_with_content.values = {k: '<redacted>' for k in notification.personalisation}

    if notification_type == SMS_TYPE:
        create_resp_partial = functools.partial(create_post_sms_response_from_notification, from_number=reply_to)
    elif notification_type == EMAIL_TYPE:
        create_resp_partial = functools.partial(
            create_post_email_response_from_notification, subject=html.unescape(template_with_content.subject)
        )
    elif notification_type == LETTER_TYPE:
        create_resp_partial = functools.partial(
            create_post_letter_response_from_notification,
            subject=template_with_content.subject,
        )

    resp = create_resp_partial(
        notification=notification,
        content=str(template_with_content),
        url_root=request.url_root,
        scheduled_for=scheduled_for,
    )

    return jsonify(resp), 201


def process_sms_or_email_notification(
    *,
    form,
    notification_type,
    api_key,
    template,
    service,
    reply_to_text=None,
    created_at: datetime | None = None,
):
    form_send_to = form['email_address' if (notification_type == EMAIL_TYPE) else 'phone_number']

    send_to = validate_and_format_recipient(
        send_to=form_send_to, key_type=api_key.key_type, service=service, notification_type=notification_type
    )

    # Do not persist or send notification to the queue if it is a simulated recipient.
    #
    # TODO (tech debt) - This value is computed using a predetermined list of e-mail addresses defined
    # to be for simulation.  A better approach might be to pass "simulated" as a parameter to
    # process_sms_or_email_notification or to mock the undesired side-effects in test code.
    simulated: bool = simulated_recipient(send_to, notification_type)

    personalisation = process_document_uploads(form.get('personalisation'), service, simulated=simulated)

    recipient_identifier = form.get('recipient_identifier')
    notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=form_send_to,
        service_id=service.id,
        personalisation=personalisation,
        notification_type=notification_type,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        client_reference=form.get('reference'),
        simulated=simulated,
        reply_to_text=reply_to_text,
        recipient_identifier=recipient_identifier,
        billing_code=form.get('billing_code'),
        sms_sender_id=form.get('sms_sender_id'),
        callback_url=form.get('callback_url'),
        created_at=created_at,
    )

    if 'scheduled_for' in form:
        persist_scheduled_notification(notification.id, form['scheduled_for'])
    else:
        if simulated:
            current_app.logger.debug('POST simulated notification for id: %s', notification.id)
        else:
            recipient_id_type = recipient_identifier.get('id_type') if recipient_identifier else None
            send_notification_to_queue(
                notification=notification,
                research_mode=service.research_mode,
                recipient_id_type=recipient_id_type,
                sms_sender_id=form.get('sms_sender_id'),
            )

    return notification


def process_notification_with_recipient_identifier(
    *,
    form,
    notification_type,
    api_key,
    template,
    service,
    reply_to_text=None,
    created_at: datetime | None = None,
):
    personalisation = process_document_uploads(form.get('personalisation'), service)

    notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        service_id=service.id,
        personalisation=personalisation,
        notification_type=notification_type,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        client_reference=form.get('reference'),
        reply_to_text=reply_to_text,
        recipient_identifier=form.get('recipient_identifier'),
        billing_code=form.get('billing_code'),
        sms_sender_id=form.get('sms_sender_id'),
        callback_url=form.get('callback_url'),
        created_at=created_at,
    )

    send_to_queue_for_recipient_info_based_on_recipient_identifier(
        notification=notification,
        id_type=form['recipient_identifier']['id_type'],
        communication_item_id=template.communication_item_id,
    )

    return notification


def process_document_uploads(
    personalisation_data,
    service,
    simulated=False,
):
    file_keys = [k for k, v in (personalisation_data or {}).items() if isinstance(v, dict) and 'file' in v]
    if not file_keys:
        return personalisation_data

    personalisation_data = personalisation_data.copy()

    if not authenticated_service.has_permissions(UPLOAD_DOCUMENT):
        raise BadRequestError(
            message='Service is not allowed to send {}'.format(
                get_public_notify_type_text(UPLOAD_DOCUMENT, plural=True)
            )
        )

    if any(personalisation_data[key].get('sending_method') == 'link' for key in file_keys):
        raise NotImplementedError()

    for key in file_keys:
        if simulated:
            personalisation_data[key] = 'simulated-attachment-url'
        else:
            sending_method = personalisation_data[key].get('sending_method', 'attach')
            file_name = personalisation_data[key]['filename']

            mimetype = extract_and_validate_mimetype(file_data=personalisation_data[key]['file'], file_name=file_name)
            try:
                attachment_id, encryption_key = attachment_store.put(
                    service_id=service.id,
                    attachment_stream=personalisation_data[key]['file'],
                    sending_method=sending_method,
                    mimetype=mimetype,
                )
            except AttachmentStoreError as e:
                raise BadRequestError(message='Unable to upload attachment object to store') from e
            else:
                personalisation_data[key]: UploadedAttachmentMetadata = {
                    'id': str(attachment_id),
                    'encryption_key': encryption_key,
                    'file_name': file_name,
                    'sending_method': sending_method,
                }

    return personalisation_data


def get_reply_to_text(
    notification_type,
    form,
    template,
):
    reply_to = None

    if notification_type == EMAIL_TYPE:
        reply_to = template.reply_to_email

    elif notification_type == SMS_TYPE:
        sms_sender_number = get_service_sms_sender_number(
            str(authenticated_service.id), form.get('sms_sender_id'), notification_type
        )
        if sms_sender_number:
            reply_to = try_validate_and_format_phone_number(sms_sender_number)
        else:
            # Get the default SMS sender reply_to
            default_sms_sender = dao_get_default_service_sms_sender_by_service_id(str(authenticated_service.id))
            reply_to = try_validate_and_format_phone_number(default_sms_sender.sms_sender)

    return reply_to


def strip_keys_from_personalisation_if_send_attach(personalisation):
    return {
        k: v for (k, v) in personalisation.items() if not (isinstance(v, dict) and v.get('sending_method') == 'attach')
    }
