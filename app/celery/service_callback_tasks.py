import json

from celery import Task
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from requests.api import request
from requests.exceptions import RequestException, HTTPError

from app import (
    notify_celery,
    encryption,
    statsd_client,
    DATETIME_FORMAT
)
from app.config import QueueNames
from app.dao.complaint_dao import fetch_complaint_by_id
from app.dao.inbound_sms_dao import dao_get_inbound_sms_by_id
from app.dao.service_callback_api_dao import (
    get_service_delivery_status_callback_api_for_service,
    get_service_complaint_callback_api_for_service
)
from app.dao.service_inbound_api_dao import get_service_inbound_api_for_service
from app.dao.service_sms_sender_dao import dao_get_sms_sender_by_service_id_and_number
from app.models import Complaint, Notification


@notify_celery.task(bind=True, name="send-delivery-status", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_delivery_status_to_service(
    self, notification_id, encrypted_status_update
):
    status_update = encryption.decrypt(encrypted_status_update)

    payload = {
        "id": str(notification_id),
        "reference": status_update['notification_client_reference'],
        "to": status_update['notification_to'],
        "status": status_update['notification_status'],
        "created_at": status_update['notification_created_at'],
        "completed_at": status_update['notification_updated_at'],
        "sent_at": status_update['notification_sent_at'],
        "notification_type": status_update['notification_type']
    }
    _send_to_service_callback_api(
        self,
        payload,
        status_update['service_callback_api_url'],
        status_update['service_callback_api_bearer_token'],
        logging_tags={
            'notification_id': str(notification_id)
        }
    )


@notify_celery.task(bind=True, name="send-complaint", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_complaint_to_service(self, complaint_data):
    complaint = encryption.decrypt(complaint_data)

    payload = {
        "notification_id": complaint['notification_id'],
        "complaint_id": complaint['complaint_id'],
        "reference": complaint['reference'],
        "to": complaint['to'],
        "complaint_date": complaint['complaint_date']
    }

    _send_to_service_callback_api(
        self,
        payload,
        complaint['service_callback_api_url'],
        complaint['service_callback_api_bearer_token'],
        logging_tags={
            'notification_id': complaint['notification_id'],
            'complaint_id': complaint['complaint_id']
        }
    )


@notify_celery.task(bind=True, name="send-complaint-to-vanotify", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_complaint_to_vanotify(self, complaint_id: str, complaint_template_name: str) -> None:
    from app.service.sender import send_notification_to_service_users
    complaint = fetch_complaint_by_id(complaint_id).one()

    try:
        send_notification_to_service_users(
            service_id=current_app.config['NOTIFY_SERVICE_ID'],
            template_id=current_app.config['EMAIL_COMPLAINT_TEMPLATE_ID'],
            personalisation={
                'notification_id': str(complaint.notification_id),
                'service_name': complaint.service.name,
                'template_name': complaint_template_name,
                'complaint_id': str(complaint.id),
                'complaint_type': complaint.complaint_type,
                'complaint_date': complaint.complaint_date.strftime(DATETIME_FORMAT)
            },
        )
        current_app.logger.info(
            f'Successfully sent complaint email to va-notify. notification_id: {complaint.notification_id}'
        )

    except Exception as e:
        current_app.logger.exception(
            f'Problem sending complaint to va-notify for notification {complaint.notification_id}: {e}'
        )


@notify_celery.task(bind=True, name="send-inbound-sms", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_inbound_sms_to_service(self, inbound_sms_id, service_id):
    inbound_api = get_service_inbound_api_for_service(service_id=service_id)
    if not inbound_api:
        current_app.logger.error(
            f'could not send inbound sms to service "{service_id}" because it does not have a callback API configured'
        )
        return

    inbound_sms = dao_get_inbound_sms_by_id(service_id=service_id, inbound_id=inbound_sms_id)
    sms_sender = dao_get_sms_sender_by_service_id_and_number(service_id=service_id, number=inbound_sms.notify_number)

    payload = {
        "id": str(inbound_sms.id),
        # TODO: should we be validating and formatting the phone number here?
        "source_number": inbound_sms.user_number,
        "destination_number": inbound_sms.notify_number,
        "message": inbound_sms.content,
        "date_received": inbound_sms.provider_date.strftime(DATETIME_FORMAT),
        "sms_sender_id": str(sms_sender.id) if sms_sender else None
    }

    _send_to_service_callback_api(
        self,
        payload,
        inbound_api.url,
        inbound_api.bearer_token,
        logging_tags={
            'inbound_sms_id': str(inbound_sms_id),
            'service_id': str(service_id)
        }
    )


def _send_to_service_callback_api(self: Task, payload: dict, url: str, token: str, logging_tags: dict) -> None:
    tags = ', '.join([f"{key}: {value}" for key, value in logging_tags.items()])
    try:
        response = request(
            method="POST",
            url=url,
            data=json.dumps(payload),
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer {}'.format(token)
            },
            timeout=60
        )
        current_app.logger.info(f"{self.name} sent to {url}, response {response.status_code}, {tags}")
        response.raise_for_status()
    except RequestException as e:
        if not isinstance(e, HTTPError) or e.response.status_code >= 500:
            current_app.logger.warning(f"Retrying: {self.name} request failed for url: {url}. exc: {e}, {tags}")
            try:
                self.retry(queue=QueueNames.RETRY)
            except self.MaxRetriesExceededError:
                current_app.logger.error(f"Retry: {self.name} has retried the max num of times for url {url}, {tags}")
        else:
            current_app.logger.error(f"Not retrying: {self.name} request failed for url: {url}. exc: {e}, {tags}")


def create_delivery_status_callback_data(notification, service_callback_api):
    from app import DATETIME_FORMAT, encryption
    data = {
        "notification_id": str(notification.id),
        "notification_client_reference": notification.client_reference,
        "notification_to": notification.to,
        "notification_status": notification.status,
        "notification_created_at": notification.created_at.strftime(DATETIME_FORMAT),
        "notification_updated_at":
            notification.updated_at.strftime(DATETIME_FORMAT) if notification.updated_at else None,
        "notification_sent_at": notification.sent_at.strftime(DATETIME_FORMAT) if notification.sent_at else None,
        "notification_type": notification.notification_type,
        "service_callback_api_url": service_callback_api.url,
        "service_callback_api_bearer_token": service_callback_api.bearer_token,
    }
    return encryption.encrypt(data)


def create_complaint_callback_data(complaint, notification, service_callback_api, recipient):
    from app import DATETIME_FORMAT, encryption
    data = {
        "complaint_id": str(complaint.id),
        "notification_id": str(notification.id),
        "reference": notification.client_reference,
        "to": recipient,
        "complaint_date": complaint.complaint_date.strftime(DATETIME_FORMAT),
        "service_callback_api_url": service_callback_api.url,
        "service_callback_api_bearer_token": service_callback_api.bearer_token,
    }
    return encryption.encrypt(data)


def check_and_queue_callback_task(notification):
    # queue callback task only if the service_callback_api exists
    service_callback_api = get_service_delivery_status_callback_api_for_service(
        service_id=notification.service_id, notification_status=notification.status
    )
    if service_callback_api:
        notification_data = create_delivery_status_callback_data(notification, service_callback_api)
        send_delivery_status_to_service.apply_async([str(notification.id), notification_data],
                                                    queue=QueueNames.CALLBACKS)


def _check_and_queue_complaint_callback_task(complaint, notification, recipient):
    # queue callback task only if the service_callback_api exists
    service_callback_api = get_service_complaint_callback_api_for_service(service_id=notification.service_id)
    if service_callback_api:
        complaint_data = create_complaint_callback_data(complaint, notification, service_callback_api, recipient)
        send_complaint_to_service.apply_async([complaint_data], queue=QueueNames.CALLBACKS)


def publish_complaint(complaint: Complaint, notification: Notification, recipient_email: str) -> bool:
    provider_name = notification.sent_by
    _check_and_queue_complaint_callback_task(complaint, notification, recipient_email)
    send_complaint_to_vanotify.apply_async(
        [str(complaint.id), notification.template.name],
        queue=QueueNames.NOTIFY
    )
    statsd_client.incr(f'callback.{provider_name}.complaint_count')
    return True
