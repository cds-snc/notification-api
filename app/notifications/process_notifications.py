import base64
import json
import uuid
from datetime import datetime

import boto3
from botocore.exceptions import ClientError
from celery import chain
from flask import current_app, g

from notifications_utils.recipients import (
    ValidatedPhoneNumber,
    format_email_address,
)
from notifications_utils.timezones import convert_local_timezone_to_utc

from app.celery import provider_tasks
from app.celery.contact_information_tasks import lookup_contact_info
from app.celery.lookup_va_profile_id_task import lookup_va_profile_id
from app.config import QueueNames
from app.constants import (
    EMAIL_TYPE,
    KEY_TYPE_TEST,
    SMS_TYPE,
    LETTER_TYPE,
    NOTIFICATION_CREATED,
)

from app.dao.notifications_dao import (
    dao_create_notification,
    dao_delete_notification_by_id,
    dao_created_scheduled_notification,
)
from app.dao.service_sms_sender_dao import (
    dao_get_service_sms_sender_by_id,
    dao_get_service_sms_sender_by_service_id_and_number,
)
from app.dao.templates_dao import TemplateHistoryData, dao_get_template_history_by_id
from app.feature_flags import is_feature_enabled, FeatureFlag
from app.models import Notification, ScheduledNotification, RecipientIdentifier, Template
from app.pii.pii_base import Pii
from app.v2.errors import BadRequestError
from app.utils import get_template_instance
from app.va.identifier import IdentifierType


def create_content_for_notification(
    template: Template,
    personalisation: dict,
):
    """
    Return an appropriate template instance from the notifications-utils repository,
    or raise BadRequestError.
    """

    utils_template_instance = get_template_instance(template.__dict__, personalisation)
    check_placeholders(utils_template_instance)

    return utils_template_instance


def check_placeholders(utils_template_instance):
    if utils_template_instance.missing_data:
        message = 'Missing personalisation: {}'.format(', '.join(utils_template_instance.missing_data))
        raise BadRequestError(fields=[{'template': message}], message=message)


def persist_notification(
    *,
    template_id,
    template_version,
    recipient=None,
    service_id,
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
    recipient_identifier: str | Pii = None,
    billing_code=None,
    sms_sender_id=None,
    callback_url=None,
) -> Notification:
    notification_created_at = created_at or datetime.utcnow()

    if notification_id is None:
        # utils sets this so we can unify logging
        # Any internal code that calls this method in a loop cannot use g (Example: send_notification_to_service_users)
        notification_id = g.request_id if getattr(g, 'request_id', '') else uuid.uuid4()

    notification = Notification(
        id=notification_id,
        template_id=template_id,
        template_version=template_version,
        to=recipient,
        service_id=service_id,
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
        billing_code=billing_code,
        sms_sender_id=sms_sender_id,
        callback_url=callback_url,
    )

    if recipient_identifier:
        # id_value is a string or Pii subclass instance.
        recipient_identifier_value = recipient_identifier['id_value']
        if is_feature_enabled(FeatureFlag.PII_ENABLED) and isinstance(recipient_identifier_value, Pii):
            recipient_identifier_value = recipient_identifier_value.get_encrypted_value()

        _recipient_identifier = RecipientIdentifier(
            notification_id=notification_id,
            id_type=recipient_identifier['id_type'],
            id_value=recipient_identifier_value,
        )

        notification.recipient_identifiers.set(_recipient_identifier)

    if notification_type == SMS_TYPE and notification.to:
        validated_recipient = ValidatedPhoneNumber(recipient)
        notification.normalised_to = validated_recipient.formatted
        notification.international = validated_recipient.international
        notification.phone_prefix = validated_recipient.country_code
        notification.rate_multiplier = validated_recipient.billable_units
    elif notification_type == EMAIL_TYPE and notification.to:
        notification.normalised_to = format_email_address(notification.to)
    elif notification_type == LETTER_TYPE:
        notification.postage = postage or template_postage

    if not simulated:
        # Persist the Notification in the database.
        dao_create_notification(notification)

        current_app.logger.info('%s %s created at %s', notification_type, notification_id, notification_created_at)

    return notification


def send_notification_to_queue(
    notification,
    research_mode,
    queue=None,
    recipient_id_type: str = None,
    sms_sender_id=None,
):
    """
    Create, enqueue, and asynchronously execute a Celery task to send a notification.
    This is the execution path for sending notifications with contact information.
    """

    tasks = []

    if recipient_id_type:
        # This query uses the cached value of the template if available.
        template: TemplateHistoryData | None = dao_get_template_history_by_id(
            str(notification.template_id), str(notification.template_version)
        )

        # This is a nullable foreign key reference to a CommunicationItem instance UUID.
        communication_item_id = None if (template is None) else template.communication_item_id

        if communication_item_id is not None:
            if recipient_id_type != IdentifierType.VA_PROFILE_ID.value:
                tasks.append(
                    lookup_va_profile_id.si(notification_id=notification.id).set(queue=QueueNames.LOOKUP_VA_PROFILE_ID)
                )

    # Including sms_sender_id is necessary so the correct sender can be chosen.
    # https://docs.celeryq.dev/en/v4.4.7/userguide/canvas.html#immutability
    deliver_task, queue = _get_delivery_task(notification, research_mode, queue, sms_sender_id)
    tasks.append(deliver_task.si(notification_id=str(notification.id), sms_sender_id=sms_sender_id).set(queue=queue))

    try:
        # This executes the task list.  Each task calls a function that makes a request to
        # the backend provider.
        chain(*tasks).apply_async()
    except Exception:
        current_app.logger.exception(
            'apply_async failed in send_notification_to_queue for notification %s.', notification.id
        )
        dao_delete_notification_by_id(notification.id)
        raise

    current_app.logger.debug(
        '%s %s sent to the %s queue for delivery', notification.notification_type, notification.id, queue
    )


def send_notification_to_queue_delayed(
    notification: Notification,
    research_mode: bool,
    queue_name: str | None = None,
    sms_sender_id: str | None = None,
    delay_seconds: int = 0,
) -> None:
    # notification sms delivery already attempted at least once so safe to skip lookup_va_profile_id
    deliver_task, queue_name = _get_delivery_task(notification, research_mode, queue_name, sms_sender_id)

    queue_prefix = current_app.config['NOTIFICATION_QUEUE_PREFIX']
    prefixed_queue_name = f'{queue_prefix}{queue_name}'

    try:
        sqs = boto3.resource('sqs', current_app.config['AWS_REGION'])
        queue = sqs.get_queue_by_name(QueueName=prefixed_queue_name)
    except ClientError:
        current_app.logger.exception(
            'ClientError, failed to create SQS resource or could not get sqs queue "%s"',
            prefixed_queue_name,
        )
        raise
    except Exception:
        current_app.logger.exception(
            'Exception, failed to create SQS resource or could not get sqs queue "%s".',
            prefixed_queue_name,
        )
        raise

    task_body = {
        'task': deliver_task.name,
        'id': str(uuid.uuid4()),
        'args': [str(notification.id), str(sms_sender_id)],
        'kwargs': {},
        'retries': 0,
    }

    envelope = {
        'body': base64.b64encode(bytes(json.dumps(task_body), 'utf-8')).decode('utf-8'),
        'content-encoding': 'utf-8',
        'content-type': 'application/json',
        'headers': {},
        'properties': {
            'reply_to': str(uuid.uuid4()),
            'correlation_id': str(uuid.uuid4()),
            'delivery_mode': 2,
            'delivery_info': {'priority': 0, 'exchange': 'default', 'routing_key': prefixed_queue_name},
            'body_encoding': 'base64',
            'delivery_tag': str(uuid.uuid4()),
        },
    }

    queue_msg = base64.b64encode(bytes(json.dumps(envelope), 'utf-8')).decode('utf-8')

    try:
        queue.send_message(MessageBody=queue_msg, DelaySeconds=delay_seconds)
        current_app.logger.debug(
            '%s %s sent to the %s queue for delivery | DelaySeconds: %s',
            notification.notification_type,
            notification.id,
            queue,
            delay_seconds,
        )

    except Exception:
        current_app.logger.exception(
            'SQS resource failed to queue message for sqs queue "%s". notification_id: %s',
            prefixed_queue_name,
            notification.id,
        )
        raise


def _get_delivery_task(
    notification: Notification,
    research_mode: bool = False,
    queue: str | None = None,
    sms_sender_id: str | None = None,
):
    """
    The return value "deliver_task" is a function decorated to be a Celery task.
    """

    if research_mode or notification.key_type == KEY_TYPE_TEST:
        queue = QueueNames.NOTIFY

    if notification.notification_type == SMS_TYPE:
        if not queue:
            queue = QueueNames.SEND_SMS

        service_sms_sender = None

        # Get the specific service_sms_sender if sms_sender_id is provided.
        # Otherwise, get the first one from the service.
        if sms_sender_id is not None:
            # This is an instance of ServiceSmsSender or None.
            service_sms_sender = dao_get_service_sms_sender_by_id(str(notification.service_id), str(sms_sender_id))
        else:
            # This is an instance of ServiceSmsSender or None.
            service_sms_sender = dao_get_service_sms_sender_by_service_id_and_number(
                notification.service_id, notification.reply_to_text
            )

        if service_sms_sender is not None and service_sms_sender.rate_limit:
            deliver_task = provider_tasks.deliver_sms_with_rate_limiting
        else:
            deliver_task = provider_tasks.deliver_sms
    elif notification.notification_type == EMAIL_TYPE:
        if not queue:
            queue = QueueNames.SEND_EMAIL
        deliver_task = provider_tasks.deliver_email
    else:
        error_message = f'Unrecognized notification type: {notification.notification_type}'
        current_app.logger.error(error_message)
        raise RuntimeError(error_message)

    return deliver_task, queue


def send_to_queue_for_recipient_info_based_on_recipient_identifier(
    notification: Notification, id_type: str, communication_item_id: uuid
) -> None:
    """
    Create, enqueue, and asynchronously execute a Celery task to send a notification.
    This is the execution path for sending notifications with recipient identifiers.
    """

    tasks = []
    if id_type != IdentifierType.VA_PROFILE_ID.value:
        tasks.append(
            lookup_va_profile_id.si(notification_id=notification.id).set(queue=QueueNames.LOOKUP_VA_PROFILE_ID),
        )

    tasks.append(lookup_contact_info.si(notification_id=notification.id).set(queue=QueueNames.LOOKUP_CONTACT_INFO))
    deliver_task, deliver_queue = _get_delivery_task(notification)
    tasks.append(deliver_task.si(notification_id=notification.id).set(queue=deliver_queue))

    try:
        # This executes the task list.  Each task calls a function that makes a request to
        # the backend provider.
        chain(*tasks).apply_async()
    except Exception:
        current_app.logger.exception(
            'apply_async failed in send_to_queue_for_recipient_info_based_on_recipient_identifier for notification %s.',
            notification.id,
        )
        dao_delete_notification_by_id(notification.id)
        raise

    current_app.logger.debug(
        '%s %s passed to tasks: %s', notification.notification_type, notification.id, [task.name for task in tasks]
    )


def simulated_recipient(
    to_address,
    notification_type,
):
    if notification_type == SMS_TYPE:
        formatted_simulated_numbers = [
            ValidatedPhoneNumber(number).formatted for number in current_app.config['SIMULATED_SMS_NUMBERS']
        ]
        return to_address in formatted_simulated_numbers
    else:
        return to_address in current_app.config['SIMULATED_EMAIL_ADDRESSES']


def persist_scheduled_notification(
    notification_id,
    scheduled_for,
):
    scheduled_datetime = convert_local_timezone_to_utc(datetime.strptime(scheduled_for, '%Y-%m-%d %H:%M'))
    scheduled_notification = ScheduledNotification(notification_id=notification_id, scheduled_for=scheduled_datetime)
    dao_created_scheduled_notification(scheduled_notification)
