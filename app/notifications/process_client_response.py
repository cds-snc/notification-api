import uuid

from datetime import datetime
from flask import current_app
from notifications_utils.template import SMSMessageTemplate

from app import statsd_client
from app.clients import ClientException
from app.clients.sms.twilio import get_twilio_responses
from app.dao import notifications_dao
from app.clients.sms.firetext import get_firetext_responses
from app.clients.sms.mmg import get_mmg_responses
from app.celery.service_callback_tasks import check_and_queue_callback_task
from app.constants import NOTIFICATION_PENDING
from app.dao.notifications_dao import dao_update_notification
from app.dao.templates_dao import dao_get_template_by_id

sms_response_mapper = {'MMG': get_mmg_responses, 'Firetext': get_firetext_responses, 'Twilio': get_twilio_responses}


def validate_callback_data(
    data,
    fields,
    client_name,
):
    errors = []
    for f in fields:
        if not str(data.get(f, '')):
            error = '{} callback failed: {} missing'.format(client_name, f)
            errors.append(error)
    return errors if len(errors) > 0 else None


def process_sms_client_response(
    status,
    provider_reference,
    client_name,
):
    success = None
    errors = None
    # validate reference
    if provider_reference == 'send-sms-code':
        success = '{} callback succeeded: send-sms-code'.format(client_name)
        return success, errors

    try:
        uuid.UUID(provider_reference, version=4)
    except ValueError:
        errors = '{} callback with invalid reference {}'.format(client_name, provider_reference)
        return success, errors

    try:
        response_parser = sms_response_mapper[client_name]
    except KeyError:
        return success, 'unknown sms client: {}'.format(client_name)

    # validate  status
    try:
        notification_status = response_parser(status)
        current_app.logger.info(
            '{} callback return status of {} for reference: {}'.format(client_name, status, provider_reference)
        )
    except KeyError:
        _process_for_status(
            notification_status='technical-failure', client_name=client_name, provider_reference=provider_reference
        )
        raise ClientException('{} callback failed: status {} not found.'.format(client_name, status))

    success = _process_for_status(
        notification_status=notification_status, client_name=client_name, provider_reference=provider_reference
    )
    return success, errors


def _process_for_status(
    notification_status,
    client_name,
    provider_reference,
) -> None | str:
    # record stats
    notification = notifications_dao.update_notification_status_by_id(
        notification_id=provider_reference, status=notification_status, sent_by=client_name.lower()
    )
    if not notification:
        return

    statsd_client.incr('callback.{}.{}'.format(client_name.lower(), notification_status))

    if notification.sent_at:
        statsd_client.timing_with_dates(
            'callback.{}.elapsed-time'.format(client_name.lower()), datetime.utcnow(), notification.sent_at
        )

    if notification.billable_units == 0:
        service = notification.service
        template_model = dao_get_template_by_id(notification.template_id, notification.template_version)

        template = SMSMessageTemplate(
            template_model.__dict__,
            values=notification.personalisation,
            prefix=service.name,
            show_prefix=service.prefix_sms,
        )
        notification.billable_units = template.fragment_count
        notifications_dao.dao_update_notification(notification)

    if notification_status != NOTIFICATION_PENDING:
        check_and_queue_callback_task(notification)

    success = '{} callback succeeded. reference {} updated'.format(client_name, provider_reference)
    return success


def set_notification_sent_by(
    notification,
    client_name,
):
    notification.sent_by = client_name
    dao_update_notification(notification)
