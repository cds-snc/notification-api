from datetime import datetime

from notifications_utils.template import SMSMessageTemplate

from app import statsd_client
from app.celery.service_callback_tasks import send_delivery_status_to_service
from app.config import QueueNames
from app.dao import notifications_dao
from app.dao.notifications_dao import dao_update_notification
from app.dao.service_callback_api_dao import (
    get_service_delivery_status_callback_api_for_service,
)
from app.dao.templates_dao import dao_get_template_by_id
from app.models import NOTIFICATION_PENDING
from app.notifications.callbacks import create_delivery_status_callback_data


def _process_for_status(notification_status, client_name, provider_reference):
    # record stats
    notification = notifications_dao.update_notification_status_by_id(
        notification_id=provider_reference,
        status=notification_status,
        sent_by=client_name.lower(),
    )
    if not notification:
        return

    statsd_client.incr("callback.{}.{}".format(client_name.lower(), notification_status))

    if notification.sent_at:
        statsd_client.timing_with_dates(
            "callback.{}.elapsed-time".format(client_name.lower()),
            datetime.utcnow(),
            notification.sent_at,
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
        service_callback_api = get_service_delivery_status_callback_api_for_service(service_id=notification.service_id)
        # queue callback task only if the service_callback_api exists
        if service_callback_api:
            signed_notification = create_delivery_status_callback_data(notification, service_callback_api)
            send_delivery_status_to_service.apply_async(
                [str(notification.id), signed_notification, notification.service_id],
                queue=QueueNames.CALLBACKS,
            )

    success = "{} callback succeeded. reference {} updated".format(client_name, provider_reference)
    return success


def set_notification_sent_by(notification, client_name):
    notification.sent_by = client_name
    dao_update_notification(notification)
