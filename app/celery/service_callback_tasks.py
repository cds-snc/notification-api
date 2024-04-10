import json

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from requests import HTTPError, RequestException, request

from app import notify_celery, signer_complaint, signer_delivery_status
from app.config import QueueNames


@notify_celery.task(bind=True, name="send-delivery-status", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_delivery_status_to_service(self, notification_id, signed_status_update):
    status_update = signer_delivery_status.verify(signed_status_update)

    data = {
        "id": str(notification_id),
        "reference": status_update["notification_client_reference"],
        "to": status_update["notification_to"],
        "status": status_update["notification_status"],
        "status_description": status_update["notification_status_description"],
        "provider_response": status_update["notification_provider_response"],
        "created_at": status_update["notification_created_at"],
        "completed_at": status_update["notification_updated_at"],
        "sent_at": status_update["notification_sent_at"],
        "notification_type": status_update["notification_type"],
    }
    _send_data_to_service_callback_api(
        self,
        data,
        status_update["service_callback_api_url"],
        status_update["service_callback_api_bearer_token"],
        "send_delivery_status_to_service",
    )


@notify_celery.task(bind=True, name="send-complaint", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_complaint_to_service(self, complaint_data):
    complaint = signer_complaint.verify(complaint_data)

    data = {
        "notification_id": complaint["notification_id"],
        "complaint_id": complaint["complaint_id"],
        "reference": complaint["reference"],
        "to": complaint["to"],
        "complaint_date": complaint["complaint_date"],
    }

    _send_data_to_service_callback_api(
        self,
        data,
        complaint["service_callback_api_url"],
        complaint["service_callback_api_bearer_token"],
        "send_complaint_to_service",
    )


def _send_data_to_service_callback_api(self, data, service_callback_url, token, function_name):
    notification_id = data["notification_id"] if "notification_id" in data else data["id"]
    try:
        response = request(
            method="POST",
            url=service_callback_url,
            data=json.dumps(data),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(token),
            },
            timeout=5,
        )
        current_app.logger.info(
            "{} sending {} to {}, response {}".format(
                function_name,
                notification_id,
                service_callback_url,
                response.status_code,
            )
        )
        response.raise_for_status()
    except RequestException as e:
        current_app.logger.warning(
            "{} request failed for notification_id: {} and url: {}. exc: {}".format(
                function_name, notification_id, service_callback_url, e
            )
        )
        if not isinstance(e, HTTPError) or e.response.status_code >= 500:
            try:
                self.retry(queue=QueueNames.CALLBACKS_RETRY)
            except self.MaxRetriesExceededError:
                current_app.logger.warning(
                    "Retry: {} has retried the max num of times for callback url {} and notification_id: {}".format(
                        function_name, service_callback_url, notification_id
                    )
                )
