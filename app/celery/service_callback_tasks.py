import json
import random

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from requests import HTTPError, RequestException, request

from app import notify_celery, signer_complaint, signer_delivery_status
from app.config import QueueNames
from app.dao.service_callback_api_dao import (
    get_service_complaint_callback_api_for_service,
    get_service_delivery_status_callback_api_for_service,
    suspend_unsuspend_service_callback_api,
)
from app.models import COMPLAINT_CALLBACK_TYPE, DELIVERY_STATUS_CALLBACK_TYPE


def _calculate_callback_retry_countdown(retries: int) -> int:
    """Compute exponential retry delay with jitter and a hard cap."""
    base_delay_seconds = max(1, int(current_app.config["CALLBACK_RETRY_BACKOFF_BASE_SECONDS"]))
    max_delay_seconds = max(base_delay_seconds, int(current_app.config["CALLBACK_RETRY_BACKOFF_MAX_SECONDS"]))
    jitter_factor = float(current_app.config["CALLBACK_RETRY_JITTER_FACTOR"])
    jitter_factor = min(max(jitter_factor, 0.0), 1.0)

    backoff_seconds = min(base_delay_seconds * (2**retries), max_delay_seconds)
    jitter_delta = backoff_seconds * jitter_factor
    jittered_seconds = random.uniform(backoff_seconds - jitter_delta, backoff_seconds + jitter_delta)

    # Keep retry delay bounded so we can tune behavior safely with config values.
    return max(1, min(max_delay_seconds, int(round(jittered_seconds))))


@notify_celery.task(bind=True, name="send-delivery-status", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_delivery_status_to_service(self, notification_id, signed_status_update, service_id):
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
        service_id,
        data,
        status_update["service_callback_api_url"],
        status_update["service_callback_api_bearer_token"],
        "send_delivery_status_to_service",
        DELIVERY_STATUS_CALLBACK_TYPE,
    )


@notify_celery.task(bind=True, name="send-complaint", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def send_complaint_to_service(self, complaint_data, service_id):
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
        service_id,
        data,
        complaint["service_callback_api_url"],
        complaint["service_callback_api_bearer_token"],
        "send_complaint_to_service",
        COMPLAINT_CALLBACK_TYPE,
    )


def _send_data_to_service_callback_api(self, service_id, data, service_callback_url, token, function_name, callback_type):
    notification_id = data["notification_id"] if "notification_id" in data else data["id"]
    callback_api = _get_service_callback_api_for_type(service_id=service_id, callback_type=callback_type)
    if not callback_api:
        current_app.logger.warning(
            f"{function_name} callback config missing for service: {service_id} callback_type: {callback_type}. "
            f"Skipping callback for notification_id: {notification_id}."
        )
        return

    if callback_api.is_suspended:
        current_app.logger.info(
            f"{function_name} callback config {callback_api.id} for service: {service_id} callback_type: {callback_type} "
            f"is suspended. Skipping callback for notification_id: {notification_id}."
        )
        return

    callback_target_url = callback_api.url
    callback_target_token = callback_api.bearer_token

    if callback_api.url != service_callback_url:
        current_app.logger.info(
            f"{function_name} callback URL changed for service: {service_id} callback_type: {callback_type}. "
            f"Current URL {callback_api.url} does not match task URL {service_callback_url}. "
            f"Rebinding callback send to current URL for notification_id: {notification_id}."
        )

    try:
        current_app.logger.info(
            "{} sending {} to {} service: {}".format(function_name, notification_id, callback_target_url, service_id)
        )
        response = request(
            method="POST",
            url=callback_target_url,
            data=json.dumps(data),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {callback_target_token}",
            },
            timeout=5,
        )

        current_app.logger.info(
            f"{function_name} sent {notification_id} to {callback_target_url} service: {service_id}, response {response.status_code}"
        )

        response.raise_for_status()
    except RequestException as e:
        current_app.logger.warning(
            f"{function_name} request failed for notification_id: {notification_id} to url: {callback_target_url} service: {service_id} exc: {e}"
        )
        # Retry if the response status code is server-side or 429 (too many requests).
        if not isinstance(e, HTTPError) or e.response.status_code >= 500 or e.response.status_code == 429:
            countdown = _calculate_callback_retry_countdown(self.request.retries)
            try:
                self.retry(queue=QueueNames.CALLBACKS_RETRY, countdown=countdown)
            except self.MaxRetriesExceededError:
                _suspend_service_callback_and_send_email(
                    service_id=service_id,
                    callback_api=callback_api,
                    callback_type=callback_type,
                    failed_callback_url=callback_target_url,
                )
                current_app.logger.warning(
                    f"Retry: {function_name} has retried the max num of times for callback url {callback_target_url} "
                    f"notification_id: {notification_id} service: {service_id}"
                )


def _get_service_callback_api_for_type(service_id, callback_type):
    if callback_type == DELIVERY_STATUS_CALLBACK_TYPE:
        return get_service_delivery_status_callback_api_for_service(service_id=service_id)
    if callback_type == COMPLAINT_CALLBACK_TYPE:
        return get_service_complaint_callback_api_for_service(service_id=service_id)

    current_app.logger.warning(f"Unknown callback type {callback_type} for service {service_id}")
    return None


def _suspend_service_callback_and_send_email(service_id, callback_api, callback_type, failed_callback_url):
    if callback_api:
        callback_api = suspend_unsuspend_service_callback_api(
            callback_api,
            updated_by_id=current_app.config["NOTIFY_USER_ID"],
            suspend=True,
            failed_callback_url=failed_callback_url,
        )
    if not callback_api:
        current_app.logger.info(
            f"Skipping callback suspension for service {service_id} callback_type {callback_type}. "
            "Callback may be missing, already suspended, or updated since this task was queued."
        )
        return

    notify_celery.send_task(
        "send-service-callback-suspension-email",
        kwargs={"service_id": str(callback_api.service_id)},
        queue=QueueNames.NOTIFY,
    )
