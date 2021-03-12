import json

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from requests import (
    HTTPError,
    request,
    RequestException
)

from app import (
    notify_celery,
    encryption
)
from app.config import QueueNames
from app.dao.service_callback_api_dao import get_service_delivery_status_callback_api_for_service, \
    get_service_complaint_callback_api_for_service
from app.models import Complaint


@notify_celery.task(bind=True, name="send-delivery-status", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_delivery_status_to_service(
    self, notification_id, encrypted_status_update
):
    status_update = encryption.decrypt(encrypted_status_update)

    data = {
        "id": str(notification_id),
        "reference": status_update['notification_client_reference'],
        "to": status_update['notification_to'],
        "status": status_update['notification_status'],
        "created_at": status_update['notification_created_at'],
        "completed_at": status_update['notification_updated_at'],
        "sent_at": status_update['notification_sent_at'],
        "notification_type": status_update['notification_type']
    }
    _send_data_to_service_callback_api(
        self,
        data,
        status_update['service_callback_api_url'],
        status_update['service_callback_api_bearer_token'],
        'send_delivery_status_to_service'
    )


@notify_celery.task(bind=True, name="send-complaint", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_complaint_to_service(self, complaint_data):
    complaint = encryption.decrypt(complaint_data)

    data = {
        "notification_id": complaint['notification_id'],
        "complaint_id": complaint['complaint_id'],
        "reference": complaint['reference'],
        "to": complaint['to'],
        "complaint_date": complaint['complaint_date']
    }

    _send_data_to_service_callback_api(
        self,
        data,
        complaint['service_callback_api_url'],
        complaint['service_callback_api_bearer_token'],
        'send_complaint_to_service'
    )


@notify_celery.task(bind=True, name="send-complaint-to-vanotify", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_complaint_to_vanotify(self, complaint_to_vanotify: Complaint) -> None:
    # create migrations
    # template = None
    # service = current_app.config['NOTIFY_SERVICE_ID']
    # email_address = None

    # happy path
    try:
        #   saved_notification = process_notifications.persist_notification(
        #     template_id=template.id,
        #     template_version=template.version,
        #     recipient=email_address,
        #     service=service,
        #     personalisation={
        #         'notification_id': complaint_notification.id
        #         'service_name': complaint_notification.service.name
        #         'template_name': complaint_notification.template.name
        #     },
        #     notification_type=EMAIL_TYPE,
        #     api_key_id=None,
        #     key_type=KEY_TYPE_NORMAL,
        #     reply_to_text=email_address,
        #     created_at=headers["date"],
        #     status=complaint_notification.status,
        #     reference=complaint_notification.reference
        # )

        # provider_tasks.deliver_email.apply_async(
        #             [str(saved_notification.id)],
        #             queue=QueueNames.SEND_EMAIL if not service.research_mode else QueueNames.RESEARCH_MODE
        current_app.logger.info("Hurray")

    # sad paths
    except Exception as e:
        current_app.logger.exception(f"Something went very wrong {e}")


def _send_data_to_service_callback_api(self, data, service_callback_url, token, function_name):
    notification_id = (data["notification_id"] if "notification_id" in data else data["id"])
    try:
        response = request(
            method="POST",
            url=service_callback_url,
            data=json.dumps(data),
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer {}'.format(token)
            },
            timeout=60
        )
        current_app.logger.info('{} sending {} to {}, response {}'.format(
            function_name,
            notification_id,
            service_callback_url,
            response.status_code
        ))
        response.raise_for_status()
    except RequestException as e:
        current_app.logger.warning(
            "{} request failed for notification_id: {} and url: {}. exc: {}".format(
                function_name,
                notification_id,
                service_callback_url,
                e
            )
        )
        if not isinstance(e, HTTPError) or e.response.status_code >= 500:
            try:
                self.retry(queue=QueueNames.RETRY)
            except self.MaxRetriesExceededError:
                current_app.logger.warning(
                    "Retry: {} has retried the max num of times for callback url {} and notification_id: {}".format(
                        function_name,
                        service_callback_url,
                        notification_id
                    )
                )


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


def _check_and_queue_callback_task(notification):
    # queue callback task only if the service_callback_api exists
    service_callback_api = get_service_delivery_status_callback_api_for_service(service_id=notification.service_id)
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
