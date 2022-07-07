import uuid
from datetime import datetime

from flask import current_app
from celery import chain

from notifications_utils.clients import redis
from notifications_utils.recipients import (
    get_international_phone_info,
    validate_and_format_phone_number,
    format_email_address
)
from notifications_utils.timezones import convert_local_timezone_to_utc

from app import redis_store
from app.celery import provider_tasks
from app.celery.lookup_recipient_communication_permissions_task import lookup_recipient_communication_permissions
from app.celery.contact_information_tasks import lookup_contact_info
from app.celery.lookup_va_profile_id_task import lookup_va_profile_id
from app.celery.onsite_notification_tasks import send_va_onsite_notification_task
from app.celery.letters_pdf_tasks import create_letters_pdf
from app.config import QueueNames
from app.dao.service_sms_sender_dao import dao_get_sms_sender_by_service_id_and_number
from app.feature_flags import accept_recipient_identifiers_enabled, is_feature_enabled, FeatureFlag

from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_TEST,
    SMS_TYPE,
    LETTER_TYPE,
    NOTIFICATION_CREATED,
    Notification,
    ScheduledNotification,
    RecipientIdentifier)
from app.dao.notifications_dao import (
    dao_create_notification,
    dao_delete_notification_by_id,
    dao_created_scheduled_notification)

from app.v2.errors import BadRequestError
from app.utils import get_template_instance
from app.va.identifier import IdentifierType


def create_content_for_notification(template, personalisation):
    template_object = get_template_instance(template.__dict__, personalisation)
    check_placeholders(template_object)

    return template_object


def check_placeholders(template_object):
    if template_object.missing_data:
        message = 'Missing personalisation: {}'.format(", ".join(template_object.missing_data))
        raise BadRequestError(fields=[{'template': message}], message=message)


def persist_notification(
        *,
        template_id,
        template_version,
        recipient=None,
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
        simulated=False,
        created_by_id=None,
        status=NOTIFICATION_CREATED,
        reply_to_text=None,
        billable_units=None,
        postage=None,
        template_postage=None,
        recipient_identifier=None,
        billing_code=None
):
    notification_created_at = created_at or datetime.utcnow()
    if not notification_id:
        notification_id = uuid.uuid4()
    notification = Notification(
        id=notification_id,
        template_id=template_id,
        template_version=template_version,
        to=recipient,
        service_id=service.id,
        service=service,
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
        billing_code=billing_code
    )
    if accept_recipient_identifiers_enabled() and recipient_identifier:
        _recipient_identifier = RecipientIdentifier(
            notification_id=notification_id,
            id_type=recipient_identifier['id_type'],
            id_value=recipient_identifier['id_value']
        )
        notification.recipient_identifiers.set(_recipient_identifier)

    if notification_type == SMS_TYPE and notification.to:
        formatted_recipient = validate_and_format_phone_number(recipient, international=True)
        recipient_info = get_international_phone_info(formatted_recipient)
        notification.normalised_to = formatted_recipient
        notification.international = recipient_info.international
        notification.phone_prefix = recipient_info.country_prefix
        notification.rate_multiplier = recipient_info.billable_units
    elif notification_type == EMAIL_TYPE and notification.to:
        notification.normalised_to = format_email_address(notification.to)
    elif notification_type == LETTER_TYPE:
        notification.postage = postage or template_postage

    # if simulated create a Notification model to return but do not persist the Notification to the dB
    if not simulated:
        dao_create_notification(notification)
        if key_type != KEY_TYPE_TEST:
            if redis_store.get(redis.daily_limit_cache_key(service.id)):
                redis_store.incr(redis.daily_limit_cache_key(service.id))

        current_app.logger.info(
            "{} {} created at {}".format(notification_type, notification_id, notification_created_at)
        )
    return notification


def send_notification_to_queue(notification, research_mode, queue=None, recipient_id_type: str = None):
    deliver_task, queue = _get_delivery_task(notification, research_mode, queue)

    template = notification.template

    if template:
        communication_item_id = template.communication_item_id

    try:
        tasks = [deliver_task.si(str(notification.id)).set(queue=queue)]
        if (recipient_id_type and communication_item_id and
           is_feature_enabled(FeatureFlag.CHECK_RECIPIENT_COMMUNICATION_PERMISSIONS_ENABLED)):

            tasks.insert(
                0,
                lookup_recipient_communication_permissions
                .si(str(notification.id))
                .set(queue=QueueNames.COMMUNICATION_ITEM_PERMISSIONS)
            )

            if recipient_id_type != IdentifierType.VA_PROFILE_ID.value:
                tasks.insert(0, lookup_va_profile_id.si(notification.id).set(queue=QueueNames.LOOKUP_VA_PROFILE_ID))

        chain(*tasks).apply_async()

    except Exception:
        dao_delete_notification_by_id(notification.id)
        raise

    current_app.logger.debug(
        "{} {} sent to the {} queue for delivery".format(notification.notification_type,
                                                         notification.id,
                                                         queue))


def _get_delivery_task(notification, research_mode=False, queue=None):
    if research_mode or notification.key_type == KEY_TYPE_TEST:
        queue = QueueNames.RESEARCH_MODE

    if notification.notification_type == SMS_TYPE:
        if not queue:
            queue = QueueNames.SEND_SMS

        sms_sender = dao_get_sms_sender_by_service_id_and_number(notification.service_id,
                                                                 notification.reply_to_text)

        if is_feature_enabled(FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED) and sms_sender and sms_sender.rate_limit:
            deliver_task = provider_tasks.deliver_sms_with_rate_limiting
        else:
            deliver_task = provider_tasks.deliver_sms
    if notification.notification_type == EMAIL_TYPE:
        if not queue:
            queue = QueueNames.SEND_EMAIL
        deliver_task = provider_tasks.deliver_email
    if notification.notification_type == LETTER_TYPE:
        if not queue:
            queue = QueueNames.CREATE_LETTERS_PDF
        deliver_task = create_letters_pdf

    return deliver_task, queue


def send_to_queue_for_recipient_info_based_on_recipient_identifier(
        notification: Notification, id_type: str, id_value: str, communication_item_id: uuid,
        onsite_enabled: bool = False
) -> None:
    deliver_task, deliver_queue = _get_delivery_task(notification)
    if id_type == IdentifierType.VA_PROFILE_ID.value:
        tasks = [
            send_va_onsite_notification_task.s(id_value, notification.template.id, onsite_enabled)
                                            .set(queue=QueueNames.SEND_ONSITE_NOTIFICATION),
            lookup_contact_info.si(notification.id).set(queue=QueueNames.LOOKUP_CONTACT_INFO),
            deliver_task.si(notification.id).set(queue=deliver_queue)
        ]
        if is_feature_enabled(FeatureFlag.CHECK_RECIPIENT_COMMUNICATION_PERMISSIONS_ENABLED) and communication_item_id:
            tasks.insert(
                len(tasks) - 1,
                lookup_recipient_communication_permissions
                .si(notification.id)
                .set(queue=QueueNames.COMMUNICATION_ITEM_PERMISSIONS)
            )

    else:
        tasks = [
            lookup_va_profile_id.si(notification.id).set(queue=QueueNames.LOOKUP_VA_PROFILE_ID),
            send_va_onsite_notification_task.s(notification.template.id, onsite_enabled)
                                            .set(queue=QueueNames.SEND_ONSITE_NOTIFICATION),
            lookup_contact_info.si(notification.id).set(queue=QueueNames.LOOKUP_CONTACT_INFO),
            deliver_task.si(notification.id).set(queue=deliver_queue)
        ]

        if is_feature_enabled(FeatureFlag.CHECK_RECIPIENT_COMMUNICATION_PERMISSIONS_ENABLED) and communication_item_id:
            tasks.insert(
                len(tasks) - 1,
                lookup_recipient_communication_permissions
                .si(notification.id)
                .set(queue=QueueNames.COMMUNICATION_ITEM_PERMISSIONS)
            )

    chain(*tasks).apply_async()

    current_app.logger.debug(
        "{} {} passed to tasks: {}".format(
            notification.notification_type,
            notification.id,
            [task.name for task in tasks]
        )
    )


def simulated_recipient(to_address, notification_type):
    if notification_type == SMS_TYPE:
        formatted_simulated_numbers = [
            validate_and_format_phone_number(number) for number in current_app.config['SIMULATED_SMS_NUMBERS']
        ]
        return to_address in formatted_simulated_numbers
    else:
        return to_address in current_app.config['SIMULATED_EMAIL_ADDRESSES']


def persist_scheduled_notification(notification_id, scheduled_for):
    scheduled_datetime = convert_local_timezone_to_utc(datetime.strptime(scheduled_for, "%Y-%m-%d %H:%M"))
    scheduled_notification = ScheduledNotification(notification_id=notification_id,
                                                   scheduled_for=scheduled_datetime)
    dao_created_scheduled_notification(scheduled_notification)
