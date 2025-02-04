"""
Tasks declared in this module must be configured in the CELERY_SETTINGS dictionary in app/config.py.
"""

from app import clients, db, notify_celery
from app.clients.email.aws_ses import AwsSesClientException
from app.clients.sms.aws_pinpoint import AwsPinpointException
from app.constants import (
    EMAIL_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT,
    SMS_TYPE,
)
from app.dao.dao_utils import get_reader_session
from app.models import (
    Notification,
    NotificationFailures,
    ServiceSmsSender,
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
from typing import Tuple, Optional

logger = get_task_logger(__name__)


def get_default_sms_sender_id(service_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Retrieves the default SMS sender ID for a given service.

    This function queries the database to find the default SMS sender associated with a specified service ID.

    Parameters:
    service_id (str): The unique identifier for the service whose default SMS sender ID is to be retrieved.

    Returns:
    Tuple[Optional[str], Optional[str]]:
        - First element is an error message or None if no error occurs.
        - Second element is the SMS sender ID (if found) or None (if not found or an error occurs).
    """
    query = select(ServiceSmsSender).where((ServiceSmsSender.service_id == service_id) & ServiceSmsSender.is_default)
    with get_reader_session() as db:
        try:
            sms_sender = db.execute(query).one().ServiceSmsSender
        except NoResultFound:
            return 'SMS sender ID was not set for the notification and no default was found.', None
        except Exception as err:
            return 'Unexpected error while retrieving the SMS sender: %s' % err, None
        else:
            if sms_sender.id is None:
                return 'Unexpected missing SMS sender ID.', None
            return (None, sms_sender.id)


# TODO 1534 - Error handler for sqlalchemy.exc.IntegrityError.  This happens when a foreign key references a nonexistent ID.
@notify_celery.task(serializer='json')
def v3_process_notification(  # noqa: C901
    request_data: dict,
    service_id: str,
    api_key_id: str,
    api_key_type: str,
):
    """
    This is the first task used to process request data send to POST /v3/notification/(email|sms).  It performs
    additional, non-schema verifications that require database queries:

    1. The specified template exists.
    2. The specified template is for the specified type of notification.
    3. The given service owns the specified template.
    """

    notification = v3_create_notification_instance(request_data, service_id, api_key_id, api_key_type)

    # TODO 1534 - Catch db connection errors and retry?
    with get_reader_session() as reader_session:
        query = select(Template).where(Template.id == request_data['template_id'])
        try:
            # TODO 1534 - This should intead use reader_session.get which returns an object or None
            template = reader_session.execute(query).one().Template
            notification.template_version = template.version
        except NoResultFound:
            notification.status = NOTIFICATION_PERMANENT_FAILURE
            notification.status_reason = 'The template does not exist.'
            err = f'Notification {notification.id} specified nonexistent template {notification.template_id}.'
            v3_persist_failed_notification(notification, err)
            return
        except MultipleResultsFound:
            notification.status = NOTIFICATION_PERMANENT_FAILURE
            notification.status_reason = 'Multiple templates found.'
            err = f'Multiple templates with id {request_data["template_id"]} found. Notification {notification.id}.'
            v3_persist_failed_notification(notification, err)
            return

    notification.template_version = template.version
    if service_id != template.service_id:
        notification.status = NOTIFICATION_PERMANENT_FAILURE
        notification.status_reason = 'The service does not own the template.'
        err = f"Service {service_id} doesn't own template {template.id}."
        v3_persist_failed_notification(notification, err)
        return

    if request_data['notification_type'] != template.template_type:
        notification.status = NOTIFICATION_PERMANENT_FAILURE
        notification.status_reason = 'The template type does not match the notification type.'
        err = f"The template type '{request_data.get('notification_type')}' does not match '{template.template_type}'."
        v3_persist_failed_notification(notification, err)
        return

    if notification.to is None:
        # Launch a new task to get the contact information from VA Profile using the recipient ID.
        # TODO 1593
        notification.status = NOTIFICATION_PERMANENT_FAILURE
        notification.status_reason = 'Sending with recipient_identifer is not yet implemented.'
        err = 'notification.to is None. Sending with recipient_identifer is not yet implemented.'
        v3_persist_failed_notification(notification, err)
        return

    if notification.notification_type == EMAIL_TYPE:
        v3_send_email_notification.delay(notification, template)
    elif notification.notification_type == SMS_TYPE:
        if notification.sms_sender_id is None:
            err, sms_sender_id = get_default_sms_sender_id(service_id)
            if err is not None:
                notification.status = NOTIFICATION_PERMANENT_FAILURE
                notification.status_reason = err
                v3_persist_failed_notification(notification, err)
                return
            notification.sms_sender_id = sms_sender_id

        # TODO 1534 - Catch db connection errors and retry?
        query = select(ServiceSmsSender).where(
            (ServiceSmsSender.id == notification.sms_sender_id) & (ServiceSmsSender.service_id == service_id)
        )
        try:
            with get_reader_session() as reader_session:
                sms_sender = reader_session.execute(query).one().ServiceSmsSender
                v3_send_sms_notification.delay(notification, sms_sender.sms_sender)
        except NoResultFound:
            err = f"SMS sender with id '{notification.sms_sender_id}' does not exist."

            # Set sms_sender_id to None so persisting it doesn't raise sqlalchemy.exc.IntegrityError
            # This happens in case user provides invalid sms_sender_id in the request data
            notification.sms_sender_id = None
            notification.status = NOTIFICATION_PERMANENT_FAILURE
            notification.status_reason = 'SMS sender does not exist.'
            v3_persist_failed_notification(notification, err)
        except MultipleResultsFound:
            err = f'Multiple SMS sender ids matched with: {notification.sms_sender_id}'

            # Set sms_sender_id to None so persisting it doesn't raise sqlalchemy.exc.IntegrityError
            # This happens in case user provides invalid sms_sender_id in the request data
            notification.sms_sender_id = None
            notification.status = NOTIFICATION_PERMANENT_FAILURE
            notification.status_reason = 'SMS sender is invalid'
            v3_persist_failed_notification(notification, err)

    return


@notify_celery.task(
    serializer='pickle',
    autoretry_for=(AwsSesClientException,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=2886,
)
def v3_send_email_notification(
    notification: Notification,
    template: Template,
):
    # TODO 1505 - Determine the provider.  For now, assume SES.
    client = clients.get_email_client('ses')
    if client is None:
        notification.status = NOTIFICATION_PERMANENT_FAILURE
        notification.status_reason = "Couldn't get the provider client."
        v3_persist_failed_notification(notification, "Couldn't get the provider client while trying to send email.")
        return

    # Persist the notification so related model instances are available to downstream code.
    notification.status = NOTIFICATION_CREATED
    db.session.add(notification)
    # TODO 1634 - Why is this necessary?  The template isn't being modified, and refreshing fails.
    # Without this "add", e-mail doesn't actually send, but deleting it causes a unit test to fail.
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
    #     **get_html_email_options(notification)
    # )

    # This might raise AwsSesClientException.
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
        reply_to_address=template.get_reply_to_text(),
    )

    notification.status = NOTIFICATION_SENT
    notification.sent_at = datetime.utcnow()
    notification.sent_by = client.get_name()
    notification.reference = provider_reference
    db.session.commit()
    return


@notify_celery.task(
    serializer='pickle',
    autoretry_for=(AwsPinpointException,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=2886,
)
def v3_send_sms_notification(
    notification: Notification,
    sender_phone_number: str,
):
    # TODO 1505 - Determine the provider.  For now, assume Pinpoint.
    client = clients.get_sms_client('pinpoint')
    if client is None:
        notification.status = NOTIFICATION_PERMANENT_FAILURE
        notification.status_reason = "Couldn't get the provider client."
        v3_persist_failed_notification(
            notification, "Client is None. Couldn't get the provider client while sending sms."
        )
        return

    # Persist the notification so related model instances are available to downstream code.
    notification.status = NOTIFICATION_CREATED
    db.session.add(notification)
    db.session.commit()

    # This might raise AwsPinpointException.
    provider_reference = client.send_sms(
        notification.to, notification.content, notification.client_reference, True, sender_phone_number
    )

    notification.status = NOTIFICATION_SENT
    notification.sent_at = datetime.utcnow()
    notification.sent_by = client.get_name()
    notification.reference = provider_reference
    db.session.commit()
    return


def v3_persist_permanent_failure(notification: Notification):
    """
    Function takes a notification object, serializes its permanent failure state,
    and stores it in the database. It creates a new `NotificationFailures` entry with
    the serialized data and associates it with the notification's ID.

    Parameters:
    - notification (Notification): The notification object with a permanent failure.

    Raises:
    - Exception: If any error occurs during serialization, database addition, or commit,
      the the database transaction is rolled back.
    """
    try:
        notification_json = notification.serialize_permanent_failure()
        notification_failure = NotificationFailures(notification_id=notification.id, body=notification_json)
        db.session.add(notification_failure)
        db.session.commit()
    except Exception as err:
        db.session.rollback()
        current_app.logger.critical("Unable to save permanent failure. Error: '%s'", err)


def v3_persist_failed_notification(
    notification: Notification,
    error_reason: str,
):
    """
    This is a helper to log and persist failed notifications that are not retriable.
    """

    assert notification.status is not None
    assert notification.status_reason is not None

    current_app.logger.error(error_reason)

    if notification.status == NOTIFICATION_PERMANENT_FAILURE:
        v3_persist_permanent_failure(notification)
    else:
        try:
            db.session.add(notification)
            db.session.commit()
        except Exception as err:
            db.session.rollback()
            current_app.logger.critical("Unable to save Notification '%s'. Error: '%s'", notification.id, err)


def v3_create_notification_instance(
    request_data: dict,
    service_id: str,
    api_key_id: str,
    api_key_type: str,
    template_version: int = None,
) -> Notification:
    """
    Create and return a Notification instance, but do not persist it in the database.  The "template_version"
    parameter is not None when used from unit tests that don't call v3_process_notification, which might change
    the value of Notification.template_version to something other than 0.
    """

    right_now = datetime.utcnow()
    return Notification(
        id=request_data['id'],
        to=request_data.get('email_address' if request_data['notification_type'] == EMAIL_TYPE else 'phone_number'),
        service_id=service_id,
        template_id=request_data['template_id'],
        template_version=template_version if (template_version is not None) else 0,
        api_key_id=api_key_id,
        key_type=api_key_type,
        notification_type=request_data['notification_type'],
        created_at=right_now,
        updated_at=right_now,
        status=NOTIFICATION_PERMANENT_FAILURE,
        status_reason=None,
        client_reference=request_data.get('client_reference'),
        reference=request_data.get('reference'),
        personalisation=request_data.get('personalisation'),
        sms_sender_id=request_data.get('sms_sender_id'),
        billing_code=request_data.get('billing_code'),
    )
