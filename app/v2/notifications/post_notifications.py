import base64
import functools

import werkzeug
from flask import request, jsonify, current_app, abort
from notifications_utils.recipients import try_validate_and_format_phone_number

from app import api_user, authenticated_service, notify_celery, attachment_store
from app.attachments.mimetype import extract_and_validate_mimetype
from app.attachments.store import AttachmentStoreError
from app.attachments.types import UploadedAttachmentMetadata
from app.celery.letters_pdf_tasks import create_letters_pdf, process_virus_scan_passed
from app.celery.research_mode_tasks import create_fake_letter_response_file
from app.config import QueueNames, TaskNames
from app.dao.notifications_dao import update_notification_status_by_reference
from app.feature_flags import accept_recipient_identifiers_enabled, is_feature_enabled, FeatureFlag
from app.letters.utils import upload_letter_pdf
from app.models import (
    SCHEDULE_NOTIFICATIONS,
    SMS_TYPE,
    EMAIL_TYPE,
    LETTER_TYPE,
    UPLOAD_DOCUMENT,
    PRIORITY,
    KEY_TYPE_TEST,
    KEY_TYPE_TEAM,
    NOTIFICATION_CREATED,
    NOTIFICATION_SENDING,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING_VIRUS_CHECK
)
from app.notifications.process_letter_notifications import (
    create_letter_notification
)
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
    check_service_email_reply_to_id,
    check_service_sms_sender_id
)
from app.schema_validation import validate
from app.v2.errors import BadRequestError
from app.v2.notifications import v2_notification_blueprint
from app.v2.notifications.create_response import (
    create_post_sms_response_from_notification,
    create_post_email_response_from_notification,
    create_post_letter_response_from_notification
)
from app.v2.notifications.notification_schemas import (
    post_sms_request,
    post_email_request,
    post_letter_request,
)
from app.utils import get_public_notify_type_text


@v2_notification_blueprint.route('/<notification_type>', methods=['POST'])
def post_notification(notification_type):  # noqa: C901
    try:
        request_json = request.get_json()
    except werkzeug.exceptions.BadRequest as e:
        raise BadRequestError(message=f"Error decoding arguments: {e.description}", status_code=400)

    if notification_type == EMAIL_TYPE:
        form = validate(request_json, post_email_request)
    elif notification_type == SMS_TYPE:
        form = validate(request_json, post_sms_request)

        if form.get("sms_sender_id") is None:
            # Use the service's default sms_sender.
            for sender in authenticated_service.service_sms_senders:
                if sender.is_default:
                    form["sms_sender_id"] = sender.id
                    break
            else:
                raise BadRequestError(
                    message="You must supply a value for sms_sender_id, or the service must have a default."
                )
    elif notification_type == LETTER_TYPE:
        form = validate(request_json, post_letter_request)
    else:
        abort(404)

    if not authenticated_service.has_permissions(notification_type):
        raise BadRequestError(message="Service is not allowed to send {}".format(
            get_public_notify_type_text(notification_type, plural=True)))

    scheduled_for = form.get("scheduled_for")

    if scheduled_for is not None:
        if not authenticated_service.has_permissions(SCHEDULE_NOTIFICATIONS):
            raise BadRequestError(message="Cannot schedule notifications (this feature is invite-only)")

    check_rate_limiting(authenticated_service, api_user)

    template, template_with_content = validate_template(
        form['template_id'],
        strip_keys_from_personalisation_if_send_attach(form.get('personalisation', {})),
        authenticated_service,
        notification_type,
    )

    onsite_enabled = template.onsite_notification

    reply_to = get_reply_to_text(notification_type, form, template)

    if notification_type == LETTER_TYPE:
        notification = process_letter_notification(
            letter_data=form,
            api_key=api_user,
            template=template,
            reply_to_text=reply_to
        )
    else:
        if "email_address" in form or "phone_number" in form:
            notification = process_sms_or_email_notification(
                form=form,
                notification_type=notification_type,
                api_key=api_user,
                template=template,
                service=authenticated_service,
                reply_to_text=reply_to
            )
        else:
            # This execution path uses a given recipient identifier to lookup the
            # recipient's e-mail address or phone number.
            if accept_recipient_identifiers_enabled():
                notification = process_notification_with_recipient_identifier(
                    form=form,
                    notification_type=notification_type,
                    api_key=api_user,
                    template=template,
                    service=authenticated_service,
                    reply_to_text=reply_to,
                    onsite_enabled=onsite_enabled
                )
            else:
                current_app.logger.debug("Sending a notification without contact information is not implemented.")
                return jsonify(result='error', message="Not Implemented"), 501

        template_with_content.values = notification.personalisation

    if notification_type == SMS_TYPE:
        create_resp_partial = functools.partial(
            create_post_sms_response_from_notification,
            from_number=reply_to
        )
    elif notification_type == EMAIL_TYPE:
        create_resp_partial = functools.partial(
            create_post_email_response_from_notification,
            subject=template_with_content.subject
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
        scheduled_for=scheduled_for
    )

    return jsonify(resp), 201


def process_sms_or_email_notification(*, form, notification_type, api_key, template, service, reply_to_text=None):
    form_send_to = form["email_address" if (notification_type == EMAIL_TYPE) else "phone_number"]

    send_to = validate_and_format_recipient(
        send_to=form_send_to,
        key_type=api_key.key_type,
        service=service,
        notification_type=notification_type
    )

    # Do not persist or send notification to the queue if it is a simulated recipient.
    #
    # TODO (tech debt) - This value is computed using a predetermined list of e-mail addresses defined
    # to be for simulation.  A better approach might be to pass "simulated" as a parameter to
    # process_sms_or_email_notification or to mock the undesired side-effects in test code.
    simulated: bool = simulated_recipient(send_to, notification_type)

    personalisation = process_document_uploads(form.get('personalisation'), service, simulated=simulated)

    recipient_identifier = form.get("recipient_identifier")
    notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=form_send_to,
        service_id=service.id,
        personalisation=personalisation,
        notification_type=notification_type,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        client_reference=form.get("reference"),
        simulated=simulated,
        reply_to_text=reply_to_text,
        recipient_identifier=recipient_identifier,
        billing_code=form.get("billing_code"),
        sms_sender_id=form.get("sms_sender_id")
    )

    if "scheduled_for" in form:
        persist_scheduled_notification(notification.id, form["scheduled_for"])
    else:
        if simulated:
            current_app.logger.debug("POST simulated notification for id: %s", notification.id)
        else:
            queue_name = QueueNames.PRIORITY if template.process_type == PRIORITY else None
            recipient_id_type = recipient_identifier.get('id_type') if recipient_identifier else None
            send_notification_to_queue(
                notification=notification,
                research_mode=service.research_mode,
                queue=queue_name,
                recipient_id_type=recipient_id_type,
                sms_sender_id=form.get("sms_sender_id")
            )

    return notification


def process_notification_with_recipient_identifier(*, form, notification_type, api_key, template, service,
                                                   reply_to_text=None, onsite_enabled: bool = False):
    personalisation = process_document_uploads(form.get('personalisation'), service)

    notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        service_id=service.id,
        personalisation=personalisation,
        notification_type=notification_type,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        client_reference=form.get("reference"),
        reply_to_text=reply_to_text,
        recipient_identifier=form.get("recipient_identifier"),
        billing_code=form.get("billing_code"),
        sms_sender_id=form.get("sms_sender_id")
    )

    send_to_queue_for_recipient_info_based_on_recipient_identifier(
        notification=notification,
        id_type=form['recipient_identifier']['id_type'],
        id_value=form['recipient_identifier']['id_value'],
        communication_item_id=template.communication_item_id,
        onsite_enabled=onsite_enabled
    )

    return notification


def process_document_uploads(personalisation_data, service, simulated=False):
    file_keys = [k for k, v in (personalisation_data or {}).items() if isinstance(v, dict) and 'file' in v]
    if not file_keys:
        return personalisation_data

    if not is_feature_enabled(FeatureFlag.EMAIL_ATTACHMENTS_ENABLED):
        raise NotImplementedError()

    personalisation_data = personalisation_data.copy()

    if not authenticated_service.has_permissions(UPLOAD_DOCUMENT):
        raise BadRequestError(message="Service is not allowed to send {}".format(
            get_public_notify_type_text(UPLOAD_DOCUMENT, plural=True)))

    if any(personalisation_data[key].get('sending_method') == 'link' for key in file_keys):
        raise NotImplementedError()

    for key in file_keys:
        if simulated:
            personalisation_data[key] = 'simulated-attachment-url'
        else:
            sending_method = personalisation_data[key].get('sending_method', 'attach')
            file_name = personalisation_data[key]['filename']

            mimetype = extract_and_validate_mimetype(
                file_data=personalisation_data[key]['file'],
                file_name=file_name
            )
            try:
                attachment_id, encryption_key = attachment_store.put(
                    service_id=service.id,
                    attachment_stream=personalisation_data[key]['file'],
                    sending_method=sending_method,
                    mimetype=mimetype
                )
            except AttachmentStoreError as e:
                raise BadRequestError(message="Unable to upload attachment object to store") from e
            else:
                personalisation_data[key]: UploadedAttachmentMetadata = {
                    'id': str(attachment_id),
                    'encryption_key': encryption_key,
                    'file_name': file_name,
                    'sending_method': sending_method
                }

    return personalisation_data


def process_letter_notification(*, letter_data, api_key, template, reply_to_text, precompiled=False):
    if api_key.key_type == KEY_TYPE_TEAM:
        raise BadRequestError(message='Cannot send letters with a team api key', status_code=403)

    if not api_key.service.research_mode and api_key.service.restricted and api_key.key_type != KEY_TYPE_TEST:
        raise BadRequestError(message='Cannot send letters when service is in trial mode', status_code=403)

    if precompiled:
        return process_precompiled_letter_notifications(letter_data=letter_data,
                                                        api_key=api_key,
                                                        template=template,
                                                        reply_to_text=reply_to_text)

    test_key = api_key.key_type == KEY_TYPE_TEST

    # if we don't want to actually send the letter, then start it off in SENDING so we don't pick it up
    status = NOTIFICATION_CREATED if not test_key else NOTIFICATION_SENDING
    queue = QueueNames.CREATE_LETTERS_PDF if not test_key else QueueNames.RESEARCH_MODE

    notification = create_letter_notification(letter_data=letter_data,
                                              template=template,
                                              api_key=api_key,
                                              status=status,
                                              reply_to_text=reply_to_text)

    create_letters_pdf.apply_async(
        [str(notification.id)],
        queue=queue
    )

    if test_key:
        if current_app.config['NOTIFY_ENVIRONMENT'] in ['preview', 'development']:
            create_fake_letter_response_file.apply_async(
                (notification.reference,),
                queue=queue
            )
        else:
            update_notification_status_by_reference(notification.reference, NOTIFICATION_DELIVERED)

    return notification


def process_precompiled_letter_notifications(*, letter_data, api_key, template, reply_to_text):
    try:
        status = NOTIFICATION_PENDING_VIRUS_CHECK
        letter_content = base64.b64decode(letter_data['content'])
    except ValueError:
        raise BadRequestError(message='Cannot decode letter content (invalid base64 encoding)', status_code=400)

    notification = create_letter_notification(letter_data=letter_data,
                                              template=template,
                                              api_key=api_key,
                                              status=status,
                                              reply_to_text=reply_to_text)

    filename = upload_letter_pdf(notification, letter_content, precompiled=True)

    current_app.logger.info("Calling task scan-file for %s.", filename)

    # call task to add the filename to anti virus queue
    if current_app.config['ANTIVIRUS_ENABLED']:
        notify_celery.send_task(
            name=TaskNames.SCAN_FILE,
            kwargs={'filename': filename},
            queue=QueueNames.ANTIVIRUS,
        )
    else:
        # stub out antivirus in dev
        process_virus_scan_passed.apply_async(
            kwargs={'filename': filename},
            queue=QueueNames.LETTERS,
        )

    return notification


def get_reply_to_text(notification_type, form, template):
    reply_to = None
    if notification_type == EMAIL_TYPE:
        if template.reply_to_email is not None:
            reply_to = template.reply_to_email
        else:
            if "email_reply_to_id" in form:
                reply_to = check_service_email_reply_to_id(
                    str(authenticated_service.id), form["email_reply_to_id"], notification_type
                )
            if reply_to is None:
                template.get_reply_to_text()

    elif notification_type == SMS_TYPE:
        sms_sender_id = check_service_sms_sender_id(
            str(authenticated_service.id), form.get("sms_sender_id"), notification_type
        )
        if sms_sender_id:
            reply_to = try_validate_and_format_phone_number(sms_sender_id)
        else:
            reply_to = template.get_reply_to_text()

    elif notification_type == LETTER_TYPE:
        reply_to = template.get_reply_to_text()

    return reply_to


def strip_keys_from_personalisation_if_send_attach(personalisation):
    return {k: v for (k, v) in personalisation.items() if
            not (type(v) is dict and v.get('sending_method') == 'attach')}
