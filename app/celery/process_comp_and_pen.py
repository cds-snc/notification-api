from dataclasses import dataclass
from uuid import uuid4

from flask import current_app
from sqlalchemy.orm.exc import NoResultFound

from notifications_utils.statsd_decorators import statsd

from app import notify_celery
from app.dao.service_sms_sender_dao import dao_get_service_sms_sender_by_id
from app.models import (
    Service,
    Template,
)
from app.notifications.send_notifications import lookup_notification_sms_setup_data, send_notification_bypass_route
from app.va.identifier import IdentifierType


@dataclass
class DynamoRecord:
    participant_id: str
    payment_amount: str
    vaprofile_id: str


@notify_celery.task(name='comp-and-pen-batch-process')
@statsd(namespace='tasks')
def comp_and_pen_batch_process(records: list[dict[str, str]]) -> None:
    """Process batches of Comp and Pen notification requests.

    Args:
        records (list[dict[str, str]]): The incoming records
    """
    current_app.logger.debug(f'comp_and_pen_batch_process records: {records}')

    # Grab all the necessary data
    try:
        service, template, sms_sender_id = lookup_notification_sms_setup_data(
            current_app.config['COMP_AND_PEN_SERVICE_ID'],
            current_app.config['COMP_AND_PEN_TEMPLATE_ID'],
            current_app.config['COMP_AND_PEN_SMS_SENDER_ID'],
        )
        reply_to_text = dao_get_service_sms_sender_by_id(str(service.id), str(sms_sender_id)).sms_sender
    except (AttributeError, NoResultFound, ValueError):
        current_app.logger.exception('Unable to send comp and pen notifications due to improper configuration')
        raise

    _send_comp_and_pen_sms(
        service,
        template,
        sms_sender_id,
        reply_to_text,
        [DynamoRecord(**item) for item in records],
        current_app.config['COMP_AND_PEN_PERF_TO_NUMBER'],
    )


def _send_comp_and_pen_sms(
    service: Service,
    template: Template,
    sms_sender_id: str,
    reply_to_text: str,
    comp_and_pen_messages: list[DynamoRecord],
    perf_to_number: str,
) -> None:
    """
    Sends scheduled SMS notifications to recipients based on the provided parameters.

    Args:
        :param service (Service): The service used to send the SMS notifications.
        :param template (Template): The template used for the SMS notifications.
        :param sms_sender_id (str): The ID of the SMS sender.
        :param reply_to_text (str): The text a Veteran can reply to.
        :param comp_and_pen_messages (list[DynamoRecord]): A list of DynamoRecord from the dynamodb table containing
            the details needed to send the messages.
        :param perf_to_number (str): The recipient's phone number.

    Raises:
        Exception: If there is an error while sending the SMS notification.
    """

    for item in comp_and_pen_messages:
        current_app.logger.debug('sending - record from dynamodb: %s', item.participant_id)

        # Use perf_to_number as the recipient if available. Otherwise, use vaprofile_id as recipient_item.
        recipient_item = (
            None
            if perf_to_number is not None
            else {
                'id_type': IdentifierType.VA_PROFILE_ID.value,
                'id_value': item.vaprofile_id,
            }
        )

        try:
            # call generic method to send messages
            send_notification_bypass_route(
                service=service,
                template=template,
                reply_to_text=reply_to_text,
                personalisation={'amount': item.payment_amount},
                sms_sender_id=sms_sender_id,
                recipient=perf_to_number,
                recipient_item=recipient_item,
                notification_id=uuid4(),
            )
        except Exception:
            current_app.logger.exception(
                'Error attempting to send Comp and Pen notification with '
                'send_comp_and_pen_sms | record from dynamodb: %s',
                item.participant_id,
            )
        else:
            if perf_to_number is not None:
                current_app.logger.info(
                    'Notification sent using Perf simulated number %s instead of vaprofile_id', perf_to_number
                )

            current_app.logger.info('Notification sent to queue for record from dynamodb: %s', item.participant_id)
