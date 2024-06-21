from uuid import UUID

from flask import current_app
from sqlalchemy.orm.exc import NoResultFound

from app.dao.services_dao import dao_fetch_service_by_id
from app.dao.templates_dao import dao_get_template_by_id
from app.exceptions import NotificationTechnicalFailureException
from app.models import KEY_TYPE_NORMAL, SMS_TYPE, Service, Template
from app.notifications.process_notifications import (
    persist_notification,
    send_notification_to_queue,
    send_to_queue_for_recipient_info_based_on_recipient_identifier,
)


def lookup_notification_sms_setup_data(
    service_id: str,
    template_id: str,
    sms_sender_id: str = None,
) -> tuple[Service, Template, str]:
    """This function looks up the information necessary to send a sms notification.

    :param service_id: the id of the service to look up
    :param template_id: the id of the template to look up
    :param sms_sender_id: the id of the sms sender to use, if not provided, will use the service default
    :return: a tuple containing the service, template, and sms sender id
    """
    try:
        service: Service = dao_fetch_service_by_id(service_id)
        template: Template = dao_get_template_by_id(template_id)
    except NoResultFound as e:
        current_app.logger.error(
            'No results found in get_notification_setup_data attempting to lookup service or template'
            ' - exception: %s',
            e,
        )
        raise
    except Exception as e:
        current_app.logger.critical(
            'Error in get_notification_setup_data attempting to lookup service or template - exception: %s',
            e,
        )
        raise

    try:
        # If this line doesn't raise ValueError, the value is a valid UUID.
        sms_sender_id = UUID(sms_sender_id)
        current_app.logger.info('Using the SMS sender ID specified in get_notification_setup_data')
    except ValueError:
        sms_sender_id = service.get_default_sms_sender_id()
        current_app.logger.info('Using the service default SMS Sender ID in get_notification_setup_data')

    return service, template, str(sms_sender_id)


def send_notification_bypass_route(
    service: Service,
    template: Template,
    notification_type: str,
    recipient: str = None,
    personalisation: dict = None,
    sms_sender_id: str = None,
    recipient_item: dict = None,
    api_key_type: str = KEY_TYPE_NORMAL,
):
    """
    This will create a notification and add it to the proper celery queue using the given parameters.
    It will use `recipient_item` if provided, otherwise it uses `recipient`

    :param service: the service sending the notification
    :param template: the template to use to send the notification
    :param notification_type: the type of notification to send (sms or email)
    :param recipient: the sms number or email address to send the notification to
    :param personalisation: a dictionary of personalisation fields to include in the notification
    :param sms_sender_id: the sms sender to use when sending an sms notification,
        Note: uses service default for sms notifications if not passed in
    :param recipient_item: a dictionary specifying 'id_type' and 'id_value'
    :param api_key_type: the api key type to use, default: 'normal'

    Raises:
        NotificationTechnicalFailureException: if recipient and recipient_item are both None,
            or if recipient_item is missing 'id_type' or 'id_value'
    """

    if recipient is None and recipient_item is None:
        current_app.logger.critical(
            'Programming error attempting to use send_notification_bypass_route, both recipient and recipient_item are '
            'None. Please check the code calling this function to ensure one of these fields is populated properly.'
        )
        raise NotificationTechnicalFailureException(
            'Cannot send notification without one of: recipient or recipient_item'
        )

    if recipient_item is not None:
        if not ('id_type' in recipient_item and 'id_value' in recipient_item):
            current_app.logger.critical(
                'Error in send_notification_bypass_route attempting to send notification using recipient_item. '
                'Must contain both "id_type" and "id_value" fields, but one or both are missing. recipient_item: %s',
                recipient_item,
            )
            raise NotificationTechnicalFailureException(
                'Error attempting to send notification using recipient_item. Must contain both "id_type" and "id_value"'
                ' fields, but one or more are missing.'
            )

    # Use the service's default sms_sender if applicable
    if notification_type == SMS_TYPE and sms_sender_id is None:
        sms_sender_id = service.get_default_sms_sender_id()

    notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=recipient,
        service_id=service.id,
        personalisation=personalisation,
        notification_type=notification_type,
        api_key_id=None,
        key_type=api_key_type,
        recipient_identifier=recipient_item,
        sms_sender_id=sms_sender_id,
    )

    if recipient_item is not None:
        current_app.logger.info(
            'sending %s notification with send_notification_bypass_route via '
            'send_to_queue_for_recipient_info_based_on_recipient_identifier, notification id %s',
            notification_type,
            notification.id,
        )

        send_to_queue_for_recipient_info_based_on_recipient_identifier(
            notification=notification,
            id_type=recipient_item['id_type'],
            id_value=recipient_item['id_value'],
            communication_item_id=template.communication_item_id,
            onsite_enabled=False,
        )

    else:
        current_app.logger.info(
            'sending %s notification with send_notification_bypass_route via send_notification_to_queue, '
            'notification id %s',
            notification_type,
            notification.id,
        )

        send_notification_to_queue(
            notification=notification,
            research_mode=False,
            queue=None,
            recipient_id_type=recipient_item.get('id_type') if recipient_item else None,
            sms_sender_id=sms_sender_id,
        )
