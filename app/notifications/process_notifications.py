import uuid
from datetime import datetime
from typing import List

from flask import current_app
from notifications_utils.clients import redis
from notifications_utils.recipients import (
    format_email_address,
    get_international_phone_info,
    validate_and_format_phone_number,
)
from notifications_utils.timezones import convert_local_timezone_to_utc

from app import redis_store
from app.celery import provider_tasks
from app.celery.letters_pdf_tasks import create_letters_pdf
from app.config import QueueNames
from app.dao.notifications_dao import (
    bulk_insert_notifications,
    dao_create_notification,
    dao_created_scheduled_notification,
    dao_delete_notifications_by_id,
)
from app.dao.services_dao import dao_fetch_service_by_id
from app.dao.templates_dao import dao_get_template_by_id
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    NOTIFICATION_CREATED,
    SMS_TYPE,
    ApiKeyType,
    Notification,
    NotificationType,
    ScheduledNotification,
    Service,
)
from app.types import VerifiedNotification
from app.utils import get_template_instance
from app.v2.errors import BadRequestError


def create_content_for_notification(template, personalisation):
    template_object = get_template_instance(template.__dict__, personalisation)
    check_placeholders(template_object)

    return template_object


def number_of_sms_fragments(template, personalisation):
    if template.template_type == "sms":
        return create_content_for_notification(template, personalisation).fragment_count
    else:
        return 0


def check_placeholders(template_object):
    if template_object.missing_data:
        message = "Missing personalisation for template ID {}: {}".format(
            template_object.id, ", ".join(template_object.missing_data)
        )
        raise BadRequestError(fields=[{"template": message}], message=message)


def persist_notification(
    *,
    template_id,
    template_version,
    recipient,
    service: Service,
    personalisation,
    notification_type,
    api_key_id,
    key_type: ApiKeyType,
    created_at=None,
    job_id=None,
    job_row_number=None,
    reference=None,
    client_reference=None,
    notification_id=None,
    simulated=False,
    created_by_id=None,
    status=NOTIFICATION_CREATED,
    reply_to_text=None,
    billable_units=None,
    postage=None,
    template_postage=None,
) -> Notification:
    notification_created_at = created_at or datetime.utcnow()
    if not notification_id:
        notification_id = uuid.uuid4()
    notification = Notification(
        id=notification_id,
        template_id=template_id,
        template_version=template_version,
        to=recipient,
        service_id=service.id,
        personalisation=personalisation,
        notification_type=notification_type,
        api_key_id=api_key_id,
        key_type=key_type,
        created_at=notification_created_at,
        job_id=job_id,
        job_row_number=job_row_number,
        client_reference=client_reference,
        reference=reference,
        created_by_id=created_by_id,
        status=status,
        reply_to_text=reply_to_text,
        billable_units=billable_units,
    )
    template = dao_get_template_by_id(template_id, template_version, use_cache=True)
    # if the template is obtained from cache a tuple will be returned where
    # the first element is the Template object and the second the template cache data
    # in the form of a dict
    if isinstance(template, tuple):
        template = template[0]
    notification.queue_name = choose_queue(
        notification=notification, research_mode=service.research_mode, queue=template.queue_to_use()
    )

    if notification_type == SMS_TYPE:
        formatted_recipient = validate_and_format_phone_number(recipient, international=True)
        recipient_info = get_international_phone_info(formatted_recipient)
        notification.normalised_to = formatted_recipient
        notification.international = recipient_info.international
        notification.phone_prefix = recipient_info.country_prefix
        notification.rate_multiplier = recipient_info.billable_units
    elif notification_type == EMAIL_TYPE:
        notification.normalised_to = format_email_address(notification.to)
    elif notification_type == LETTER_TYPE:
        notification.postage = postage or template_postage

    # if simulated create a Notification model to return but do not persist the Notification to the dB
    if not simulated:
        dao_create_notification(notification)
        if key_type != KEY_TYPE_TEST:
            if redis_store.get(redis.daily_limit_cache_key(service.id)):
                redis_store.incr(redis.daily_limit_cache_key(service.id))
        current_app.logger.info("{} {} created at {}".format(notification_type, notification_id, notification_created_at))
    return notification


def transform_notification(
    *,
    template_id,
    template_version,
    recipient,
    service,
    personalisation,
    notification_type,
    api_key_id,
    key_type,
    created_at=None,
    job_id=None,
    job_row_number=None,
    reference=None,
    client_reference=None,
    notification_id=None,
    created_by_id=None,
    status=NOTIFICATION_CREATED,
    reply_to_text=None,
    billable_units=None,
    postage=None,
    template_postage=None,
) -> Notification:
    notification_created_at = created_at or datetime.utcnow()
    if not notification_id:
        notification_id = uuid.uuid4()
    notification = Notification(
        id=notification_id,
        template_id=template_id,
        template_version=template_version,
        to=recipient,
        service_id=service.id,
        personalisation=personalisation,
        notification_type=notification_type,
        api_key_id=api_key_id,
        key_type=key_type,
        created_at=notification_created_at,
        job_id=job_id,
        job_row_number=job_row_number,
        client_reference=client_reference,
        reference=reference,
        created_by_id=created_by_id,
        status=status,
        reply_to_text=reply_to_text,
        billable_units=billable_units,
    )

    if notification_type == SMS_TYPE:
        formatted_recipient = validate_and_format_phone_number(recipient, international=True)
        recipient_info = get_international_phone_info(formatted_recipient)
        notification.normalised_to = formatted_recipient
        notification.international = recipient_info.international
        notification.phone_prefix = recipient_info.country_prefix
        notification.rate_multiplier = recipient_info.billable_units
    elif notification_type == EMAIL_TYPE:
        notification.normalised_to = format_email_address(notification.to)
        notification.international = False
    elif notification_type == LETTER_TYPE:
        notification.postage = postage or template_postage

    return notification


def db_save_and_send_notification(notification: Notification):
    dao_create_notification(notification)
    if notification.key_type != KEY_TYPE_TEST:
        service_id = notification.service_id
        if redis_store.get(redis.daily_limit_cache_key(service_id)):
            redis_store.incr(redis.daily_limit_cache_key(service_id))

    current_app.logger.info(f"{notification.notification_type} {notification.id} created at {notification.created_at}")

    deliver_task = choose_deliver_task(notification)
    try:
        deliver_task.apply_async([str(notification.id)], queue=notification.queue_name)
    except Exception:
        dao_delete_notifications_by_id(notification.id)
        raise
    current_app.logger.info(
        f"{notification.notification_type} {notification.id} sent to the {notification.queue_name} queue for delivery"
    )


def choose_queue(notification, research_mode, queue=None) -> QueueNames:
    if research_mode or notification.key_type == KEY_TYPE_TEST:
        queue = QueueNames.RESEARCH_MODE

    if notification.notification_type == SMS_TYPE:
        if notification.sends_with_custom_number():
            queue = QueueNames.SEND_THROTTLED_SMS
        if not queue:
            queue = QueueNames.SEND_SMS_MEDIUM
    if notification.notification_type == EMAIL_TYPE:
        if not queue:
            queue = QueueNames.SEND_EMAIL
    if notification.notification_type == LETTER_TYPE:
        if not queue:
            queue = QueueNames.CREATE_LETTERS_PDF

    return queue


def choose_deliver_task(notification):
    if notification.notification_type == SMS_TYPE:
        deliver_task = provider_tasks.deliver_sms
        if notification.sends_with_custom_number():
            deliver_task = provider_tasks.deliver_throttled_sms
    if notification.notification_type == EMAIL_TYPE:
        deliver_task = provider_tasks.deliver_email
    if notification.notification_type == LETTER_TYPE:
        deliver_task = create_letters_pdf

    return deliver_task


def send_notification_to_queue(notification, research_mode, queue=None):
    if research_mode or notification.key_type == KEY_TYPE_TEST:
        queue = QueueNames.RESEARCH_MODE

    if notification.notification_type == SMS_TYPE:
        deliver_task = provider_tasks.deliver_sms
        if notification.sends_with_custom_number():
            deliver_task = provider_tasks.deliver_throttled_sms
            queue = QueueNames.SEND_THROTTLED_SMS
        if not queue or queue == QueueNames.NORMAL:
            queue = QueueNames.SEND_SMS_MEDIUM
    if notification.notification_type == EMAIL_TYPE:
        if not queue or queue == QueueNames.NORMAL:
            queue = QueueNames.SEND_EMAIL
        deliver_task = provider_tasks.deliver_email
    if notification.notification_type == LETTER_TYPE:
        if not queue or queue == QueueNames.NORMAL:
            queue = QueueNames.CREATE_LETTERS_PDF
        deliver_task = create_letters_pdf

    try:
        deliver_task.apply_async([str(notification.id)], queue=queue)
    except Exception:
        dao_delete_notifications_by_id(notification.id)
        raise

    current_app.logger.info(
        "------ ---- {} {} sent to the {} queue for delivery".format(notification.notification_type, notification.id, queue)
    )
    # TODO: once we've cleaned up all the unused code paths and ensured that this warning never occurs we can delete
    # the warning as well as the above calculation of queue.
    if notification.queue_name != queue:
        current_app.logger.info(
            f"Warning: notification {notification.id} has queue_name {notification.queue_name} but was sent to queue {queue}"
        )


def persist_notifications(notifications: List[VerifiedNotification]) -> List[Notification]:
    """
    Persist Notifications takes a list of json objects and creates a list of Notifications
    that gets bulk inserted into the DB.
    """

    lofnotifications = []

    for notification in notifications:
        notification_created_at = notification.get("created_at") or datetime.utcnow()
        notification_id = notification.get("notification_id", uuid.uuid4())
        notification_recipient = notification.get("recipient") or notification.get("to")
        service_id = notification.get("service").id if notification.get("service") else None  # type: ignore
        # todo: potential bug. notification_obj is being created using some keys that don't exist on notification
        # reference, created_by_id, status, billable_units aren't keys on notification at this point
        notification_obj = Notification(
            id=notification_id,
            template_id=notification.get("template_id"),
            template_version=notification.get("template_version"),
            to=notification_recipient,
            service_id=service_id,
            personalisation=notification.get("personalisation"),
            notification_type=notification.get("notification_type"),
            api_key_id=notification.get("api_key_id"),
            key_type=notification.get("key_type"),
            created_at=notification_created_at,
            job_id=notification.get("job_id"),
            job_row_number=notification.get("job_row_number"),
            client_reference=notification.get("client_reference"),
            reference=notification.get("reference"),  # type: ignore
            created_by_id=notification.get("created_by_id"),  # type: ignore
            status=notification.get("status"),  # type: ignore
            reply_to_text=notification.get("reply_to_text"),
            billable_units=notification.get("billable_units"),  # type: ignore
        )
        template = dao_get_template_by_id(notification_obj.template_id, notification_obj.template_version, use_cache=True)
        # if the template is obtained from cache a tuple will be returned where
        # the first element is the Template object and the second the template cache data
        # in the form of a dict
        if isinstance(template, tuple):
            template = template[0]
        service = dao_fetch_service_by_id(service_id, use_cache=True)
        notification_obj.queue_name = choose_queue(
            notification=notification_obj, research_mode=service.research_mode, queue=template.queue_to_use()
        )

        if notification.get("notification_type") == SMS_TYPE:
            formatted_recipient = validate_and_format_phone_number(notification_recipient, international=True)
            recipient_info = get_international_phone_info(formatted_recipient)
            notification_obj.normalised_to = formatted_recipient
            notification_obj.international = recipient_info.international
            notification_obj.phone_prefix = recipient_info.country_prefix
            notification_obj.rate_multiplier = recipient_info.billable_units
        elif notification.get("notification_type") == EMAIL_TYPE:
            notification_obj.normalised_to = format_email_address(notification_recipient)
        elif notification.get("notification_type") == LETTER_TYPE:
            notification_obj.postage = notification.get("postage") or notification.get("template_postage")  # type: ignore

        lofnotifications.append(notification_obj)
        if notification.get("key_type") != KEY_TYPE_TEST:
            service_id = notification.get("service").id  # type: ignore
            if redis_store.get(redis.daily_limit_cache_key(service_id)):
                redis_store.incr(redis.daily_limit_cache_key(service_id))

        current_app.logger.info(
            "{} {} created at {}".format(
                notification.get("notification_type"),
                notification.get("notification_id"),
                notification.get("notification_created_at"),  # type: ignore
            )
        )
    bulk_insert_notifications(lofnotifications)
    return lofnotifications


def simulated_recipient(to_address: str, notification_type: NotificationType) -> bool:
    if notification_type == SMS_TYPE:
        formatted_simulated_numbers = [
            validate_and_format_phone_number(number) for number in current_app.config["SIMULATED_SMS_NUMBERS"]
        ]
        return to_address in formatted_simulated_numbers
    else:
        return to_address in current_app.config["SIMULATED_EMAIL_ADDRESSES"]


def persist_scheduled_notification(notification_id, scheduled_for):
    scheduled_datetime = convert_local_timezone_to_utc(datetime.strptime(scheduled_for, "%Y-%m-%d %H:%M"))
    scheduled_notification = ScheduledNotification(notification_id=notification_id, scheduled_for=scheduled_datetime)
    dao_created_scheduled_notification(scheduled_notification)
