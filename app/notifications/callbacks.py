from app.celery.service_callback_tasks import send_delivery_status_to_service
from app.config import QueueNames
from app.dao.service_callback_api_dao import (
    get_service_delivery_status_callback_api_for_service,
)


def _check_and_queue_callback_task(notification):
    # queue callback task only if the service_callback_api exists
    service_callback_api = get_service_delivery_status_callback_api_for_service(service_id=notification.service_id)
    if service_callback_api:
        notification_data = create_delivery_status_callback_data(notification, service_callback_api)
        send_delivery_status_to_service.apply_async([str(notification.id), notification_data], queue=QueueNames.CALLBACKS)


def create_delivery_status_callback_data(notification, service_callback_api):
    from app import DATETIME_FORMAT, signer_delivery_status

    data = {
        "notification_id": str(notification.id),
        "notification_client_reference": notification.client_reference,
        "notification_to": notification.to,
        "notification_status": notification.status,
        "notification_status_description": notification.formatted_status,
        "notification_provider_response": notification.provider_response,
        "notification_created_at": notification.created_at.strftime(DATETIME_FORMAT),
        "notification_updated_at": notification.updated_at.strftime(DATETIME_FORMAT) if notification.updated_at else None,
        "notification_sent_at": notification.sent_at.strftime(DATETIME_FORMAT) if notification.sent_at else None,
        "notification_type": notification.notification_type,
        "service_callback_api_url": service_callback_api.url,
        "service_callback_api_bearer_token": service_callback_api.bearer_token,
    }

    return signer_delivery_status.sign(data)


def create_complaint_callback_data(complaint, notification, service_callback_api, recipient):
    from app import DATETIME_FORMAT, signer_complaint

    data = {
        "complaint_id": str(complaint.id),
        "notification_id": str(notification.id),
        "reference": notification.client_reference,
        "to": recipient,
        "complaint_date": complaint.complaint_date.strftime(DATETIME_FORMAT),
        "service_callback_api_url": service_callback_api.url,
        "service_callback_api_bearer_token": service_callback_api.bearer_token,
    }

    return signer_complaint.sign(data)
