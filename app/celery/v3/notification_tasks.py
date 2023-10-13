"""
Tasks declared in this module must be configured in the CELERY_SETTINGS dictionary in app/config.py.
"""

# TODO - Should I continue using notify_celery?  It has side-effects.
from app import clients, db, notify_celery
from app.dao.dao_utils import get_reader_session
from app.models import (
    EMAIL_TYPE,
    Notification,
    NOTIFICATION_CREATED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT,
    NOTIFICATION_TECHNICAL_FAILURE,
    ServiceSmsSender,
    SMS_TYPE,
    Template,
)
from app.service.utils import compute_source_email_address
from celery.utils.log import get_task_logger
from datetime import datetime
from flask import current_app
from notifications_utils.recipients import validate_and_format_email_address
# from notifications_utils.template import HTMLEmailTemplate, PlainTextEmailTemplate
from sqlalchemy import select
from sqlalchemy.exc import MultipleResultsFound, NoResultFound

logger = get_task_logger(__name__)


# TODO - Error handler for sqlalchemy.exc.IntegrityError.  This happens when a foreign key references a nonexistent ID.
@notify_celery.task(serializer="json")
def v3_process_notification(request_data: dict, service_id: str, api_key_id: str, api_key_type: str):
    """
    This is the first task used to process request data send to POST /v3/notification/(email|sms).  It performs
    additional, non-schema verifications that require database queries:

    1. The specified template exists.
    2. The specified template is for the specified type of notification.
    3. The given service owns the specified template.
    """

    right_now = datetime.utcnow()
    notification = Notification(
        id=request_data["id"],
        to=request_data.get("email_address" if request_data["notification_type"] == EMAIL_TYPE else "phone_number"),
        service_id=service_id,
        template_id=request_data["template_id"],
        template_version=0,
        api_key_id=api_key_id,
        key_type=api_key_type,
        notification_type=request_data["notification_type"],
        created_at=right_now,
        updated_at=right_now,
        status=NOTIFICATION_PERMANENT_FAILURE,
        client_reference=request_data.get("client_reference"),
        reference=request_data.get("reference"),
        personalisation=request_data.get("personalisation"),
        sms_sender_id=request_data.get("sms_sender_id"),
        billing_code=request_data.get("billing_code")
    )

    # TODO - Catch db connection errors and retry?
    query = select(Template).where(Template.id == request_data["template_id"])
    with get_reader_session() as reader_session:
        try:
            template = reader_session.execute(query).one().Template
            notification.template_version = template.version
        except (MultipleResultsFound, NoResultFound):
            notification.status_reason = "The template does not exist."
            # TODO - This isn't an option right now because Notification.template_id is non-nullable and
            # must reference a valid template.
            # db.session.add(notification)
            # db.session.commit()
            # TODO - Delete logging when the above issue is remedied.
            current_app.logger.error(
                "Notification %s specified nonexistent template %s.", notification.id, notification.template_id
            )
            return

    notification.template_version = template.version
    if service_id != template.service_id:
        notification.status_reason = "The service does not own the template."
        db.session.add(notification)
        db.session.commit()
        return

    if request_data["notification_type"] != template.template_type:
        notification.status_reason = "The template type does not match the notification type."
        db.session.add(notification)
        db.session.commit()
        return

    if notification.to is None:
        # Launch a new task to get the contact information from VA Profile using the recipient ID.
        # TODO
        notification.status = NOTIFICATION_TECHNICAL_FAILURE
        notification.status_reason = "Sending with recipient_identifer is not yet implemented."
        db.session.add(notification)
        db.session.commit()
        return

    if notification.notification_type == EMAIL_TYPE:
        v3_send_email_notification.delay(notification, template)
    elif notification.notification_type == SMS_TYPE:
        if notification.sms_sender_id is None:
            # Get the template or service default sms_sender_id.
            # TODO
            notification.status = NOTIFICATION_TECHNICAL_FAILURE
            notification.status_reason = "Default logic for sms_sender_id is not yet implemented."
            db.session.add(notification)
            db.session.commit()
            return

        # TODO - Catch db connection errors and retry?
        query = select(ServiceSmsSender).where(ServiceSmsSender.id == request_data["sms_sender_id"])
        try:
            with get_reader_session() as reader_session:
                sms_sender = reader_session.execute(query).one().ServiceSmsSender
                v3_send_sms_notification.delay(notification, sms_sender.sms_sender)
        except (MultipleResultsFound, NoResultFound):
            notification.status_reason = f"SMS sender {notification.sms_sender_id} does not exist."
            # Set sms_sender_id to None so persisting it doesn't raise sqlalchemy.exc.IntegrityError.
            notification.sms_sender_id = None
            db.session.add(notification)
            db.session.commit()

    return


# TODO - retry conditions
# TODO - error handling
@notify_celery.task(serializer="pickle")
def v3_send_email_notification(notification: Notification, template: Template):
    # TODO - Determine the provider.  For now, assume SES.
    # TODO - test "client is None"
    client = clients.get_email_client("ses")

    # Persist the notification so related model instances are available to downstream code.
    notification.status = NOTIFICATION_CREATED
    db.session.add(notification)
    db.session.add(template)
    db.session.commit()

    # query = select(Template).where(
    #     Template.id == notification.template_id,
    #     Template.version == notification.template_version
    # )
    # with get_reader_session() as reader_session:
    #     template_dict = reader_session.execute(query).mappings().all()[0]

    # personlization_data = notification.personalisation.copy()

    # plain_text_email = PlainTextEmailTemplate(
    #     template_dict,
    #     template.serialize(),
    #     values=personlization_data
    # )

    # html_email = HTMLEmailTemplate(
    #    template_dict,
    #    template,
    #    values=personlization_data,
    #     **get_html_email_options(notification, client)
    # )

    provider_reference = client.send_email(
        compute_source_email_address(notification.service, client),
        validate_and_format_email_address(notification.to),
        notification.subject,
        # str(plain_text_email),
        notification.content,
        # html_body=str(html_email),
        notification.content,
        # reply_to_address=validate_and_format_email_address(
        #     notification.reply_to_text if notification.reply_to_text else ''
        # )
        reply_to_address=template.get_reply_to_text()
    )

    notification.status = NOTIFICATION_SENT
    notification.sent_at = datetime.utcnow()
    notification.sent_by = client.get_name()
    notification.reference = provider_reference
    db.session.commit()


# TODO - retry conditions
# TODO - error handling
@notify_celery.task(serializer="pickle")
def v3_send_sms_notification(notification: Notification, sender_phone_number: str):
    # TODO - Determine the provider.  For now, assume Pinpoint.
    # TODO - test "client is None"
    client = clients.get_sms_client("pinpoint")

    # Persist the notification so related model instances are available to downstream code.
    notification.status = NOTIFICATION_CREATED
    db.session.add(notification)
    db.session.commit()

    # This might raise AwsPinpointException.
    # TODO - Conditional retry based on exception details.
    provider_reference = client.send_sms(
        notification.to,
        notification.content,
        notification.client_reference,
        True,
        sender_phone_number
    )

    notification.status = NOTIFICATION_SENT
    notification.sent_at = datetime.utcnow()
    notification.sent_by = client.get_name()
    notification.reference = provider_reference
    db.session.commit()
