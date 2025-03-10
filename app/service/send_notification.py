from flask import current_app
from notifications_utils.s3 import S3ObjectNotFound
from notifications_utils.s3 import s3download as utils_s3download
from sqlalchemy.orm.exc import NoResultFound

from app import create_random_identifier
from app.config import Priorities, QueueNames
from app.dao.notifications_dao import _update_notification_status
from app.dao.service_email_reply_to_dao import dao_get_reply_to_by_id
from app.dao.service_sms_sender_dao import dao_get_service_sms_senders_by_id
from app.dao.services_dao import dao_fetch_service_by_id
from app.dao.templates_dao import (
    dao_get_template_by_id_and_service_id,
    get_precompiled_letter_template,
)
from app.dao.users_dao import get_user_by_id
from app.letters.utils import (
    get_letter_pdf_filename,
    get_page_count,
    move_uploaded_pdf_to_letters_bucket,
)
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_NORMAL,
    LETTER_TYPE,
    NOTIFICATION_DELIVERED,
    SMS_TYPE,
    UPLOAD_LETTERS,
)
from app.notifications.process_notifications import (
    persist_notification,
    send_notification_to_queue,
    simulated_recipient,
)
from app.notifications.validators import (
    check_email_annual_limit,
    check_email_daily_limit,
    check_service_has_permission,
    check_service_over_daily_message_limit,
    check_sms_annual_limit,
    check_sms_daily_limit,
    increment_email_daily_count_send_warnings_if_needed,
    increment_sms_daily_count_send_warnings_if_needed,
    validate_and_format_recipient,
    validate_template,
)
from app.utils import get_delivery_queue_for_template
from app.v2.errors import BadRequestError


def validate_created_by(service, created_by_id):
    user = get_user_by_id(created_by_id)
    if service not in user.services:
        message = 'Can’t create notification - {} is not part of the "{}" service'.format(user.name, service.name)
        raise BadRequestError(message=message)


def create_one_off_reference(template_type):
    if template_type == LETTER_TYPE:
        return create_random_identifier()
    return None


def send_one_off_notification(service_id, post_data):
    service = dao_fetch_service_by_id(service_id)
    template = dao_get_template_by_id_and_service_id(template_id=post_data["template_id"], service_id=service_id)

    personalisation = post_data.get("personalisation", None)

    _, template_with_content = validate_template(template.id, personalisation, service, template.template_type)

    if template.template_type == SMS_TYPE:
        is_test_notification = simulated_recipient(post_data["to"], template.template_type)
        if not is_test_notification:
            check_sms_annual_limit(service, 1)
            check_sms_daily_limit(service, 1)
    elif template.template_type == EMAIL_TYPE:
        check_email_annual_limit(service, 1)
        check_email_daily_limit(service, 1)  # 1 email

    validate_and_format_recipient(
        send_to=post_data["to"],
        key_type=KEY_TYPE_NORMAL,
        service=service,
        notification_type=template.template_type,
        allow_safelisted_recipients=False,
    )

    validate_created_by(service, post_data["created_by"])

    if template.template_type == SMS_TYPE:
        is_test_notification = simulated_recipient(post_data["to"], template.template_type)
        if not is_test_notification:
            increment_sms_daily_count_send_warnings_if_needed(service, 1)
    elif template.template_type == EMAIL_TYPE:
        increment_email_daily_count_send_warnings_if_needed(service, 1)  # 1 email

    sender_id = post_data.get("sender_id", None)
    reply_to = get_reply_to_text(
        notification_type=template.template_type,
        sender_id=sender_id,
        service=service,
        template=template,
    )
    notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        template_postage=template.postage,
        recipient=post_data["to"],
        service=service,
        personalisation=personalisation,
        notification_type=template.template_type,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        created_by_id=post_data["created_by"],
        reply_to_text=reply_to,
        reference=create_one_off_reference(template.template_type),
    )

    if template.template_type == LETTER_TYPE and service.research_mode:
        _update_notification_status(
            notification,
            NOTIFICATION_DELIVERED,
        )
    else:
        # allow one-off sends from admin to go quicker by using normal queue instead of bulk queue
        queue = get_delivery_queue_for_template(template)
        if queue == QueueNames.DELIVERY_QUEUES[template.template_type][Priorities.LOW]:
            queue = QueueNames.DELIVERY_QUEUES[template.template_type][Priorities.MEDIUM]

        send_notification_to_queue(
            notification=notification,
            research_mode=service.research_mode,
            queue=queue,
        )

    return {"id": str(notification.id)}


def get_reply_to_text(notification_type, sender_id, service, template):
    reply_to = None
    if sender_id:
        try:
            if notification_type == EMAIL_TYPE:
                message = "Reply to email address not found"
                reply_to = dao_get_reply_to_by_id(service.id, sender_id).email_address
            elif notification_type == SMS_TYPE:
                message = "SMS sender not found"
                reply_to = dao_get_service_sms_senders_by_id(service.id, sender_id).get_reply_to_text()
        except NoResultFound:
            raise BadRequestError(message=message)
    else:
        reply_to = template.get_reply_to_text()
    return reply_to


def send_pdf_letter_notification(service_id, post_data):
    service = dao_fetch_service_by_id(service_id)

    check_service_has_permission(LETTER_TYPE, service.permissions)
    check_service_has_permission(UPLOAD_LETTERS, service.permissions)
    check_service_over_daily_message_limit(KEY_TYPE_NORMAL, service)
    validate_created_by(service, post_data["created_by"])

    template = get_precompiled_letter_template(service.id)
    file_location = "service-{}/{}.pdf".format(service.id, post_data["file_id"])

    try:
        letter = utils_s3download(current_app.config["TRANSIENT_UPLOADED_LETTERS"], file_location)
    except S3ObjectNotFound as e:
        current_app.logger.exception(
            "Letter {}.pdf not in transient {} bucket".format(
                post_data["file_id"], current_app.config["TRANSIENT_UPLOADED_LETTERS"]
            )
        )
        raise e

    # Getting the page count won't raise an error since admin has already checked the PDF is valid
    billable_units = get_page_count(letter.read())

    personalisation = {"address_line_1": post_data["filename"]}

    # TODO: stop hard-coding postage as 'second' once we get postage from the admin
    notification = persist_notification(
        notification_id=post_data["file_id"],
        template_id=template.id,
        template_version=template.version,
        template_postage=template.postage,
        recipient=post_data["filename"],
        service=service,
        personalisation=personalisation,
        notification_type=LETTER_TYPE,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        reference=create_one_off_reference(LETTER_TYPE),
        client_reference=post_data["filename"],
        created_by_id=post_data["created_by"],
        billable_units=billable_units,
        postage="second",
    )

    upload_filename = get_letter_pdf_filename(
        notification.reference,
        notification.service.crown,
        is_scan_letter=False,
        postage=notification.postage,
    )

    move_uploaded_pdf_to_letters_bucket(file_location, upload_filename)

    return {"id": str(notification.id)}
