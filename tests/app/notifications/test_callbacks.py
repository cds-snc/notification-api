from datetime import datetime
from unittest.mock import patch

from app import DATETIME_FORMAT, signer_complaint, signer_delivery_status
from app.notifications.callbacks import (
    _check_and_queue_callback_task,
    create_complaint_callback_data,
    create_delivery_status_callback_data,
)
from tests.app.conftest import create_sample_notification
from tests.app.db import create_complaint, create_service_callback_api


def test_create_delivery_status_callback_data(
    notify_db,
    notify_db_session,
    sample_email_template,
):
    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        status="sending",
        sent_at=datetime.utcnow(),
    )
    callback_api = create_service_callback_api(service=sample_email_template.service, url="https://original_url.com")

    assert signer_delivery_status.verify(create_delivery_status_callback_data(notification, callback_api)) == {
        "notification_client_reference": notification.client_reference,
        "notification_created_at": notification.created_at.strftime(DATETIME_FORMAT),
        "notification_id": str(notification.id),
        "notification_provider_response": notification.provider_response,
        "notification_sent_at": notification.sent_at.strftime(DATETIME_FORMAT),
        "notification_status": notification.status,
        "notification_status_description": notification.formatted_status,
        "notification_to": notification.to,
        "notification_type": notification.notification_type,
        "notification_updated_at": notification.updated_at,
        "service_callback_api_bearer_token": callback_api.bearer_token,
        "service_callback_api_url": callback_api.url,
    }


def test_create_complaint_callback_data(
    notify_db,
    notify_db_session,
    sample_email_template,
):
    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        status="delivered",
        sent_at=datetime.utcnow(),
    )
    complaint = create_complaint(notification=notification, service=notification.service)
    callback_api = create_service_callback_api(service=sample_email_template.service, url="https://original_url.com")

    assert signer_complaint.verify(
        create_complaint_callback_data(complaint, notification, callback_api, "recipient@example.com")
    ) == {
        "complaint_id": str(complaint.id),
        "notification_id": str(notification.id),
        "reference": notification.client_reference,
        "to": "recipient@example.com",
        "complaint_date": complaint.complaint_date.strftime(DATETIME_FORMAT),
        "service_callback_api_url": callback_api.url,
        "service_callback_api_bearer_token": callback_api.bearer_token,
    }


def test_check_and_queue_callback_task_calls_delivery_task(
    notify_db,
    notify_db_session,
    sample_email_template,
):
    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        status="sending",
    )
    callback_api = create_service_callback_api(service=sample_email_template.service, url="https://original_url.com")

    with patch("app.notifications.callbacks.send_delivery_status_to_service.apply_async") as mock_apply_async:
        _check_and_queue_callback_task(notification)

        mock_apply_async.assert_called_once_with(
            [str(notification.id), create_delivery_status_callback_data(notification, callback_api)],
            queue="service-callbacks",
        )


def test_check_and_queue_callback_task_does_not_call_delivery_task_when_service_callback_api_is_suspended(
    notify_db,
    notify_db_session,
    sample_email_template,
):
    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        status="sending",
    )
    create_service_callback_api(service=sample_email_template.service, url="https://original_url.com", is_suspended=True)

    with patch("app.notifications.callbacks.send_delivery_status_to_service.apply_async") as mock_apply_async:
        _check_and_queue_callback_task(notification)
        mock_apply_async.assert_not_called()


def test_check_and_queue_callback_task_does_not_call_delivery_task_when_notification_is_empty(
    sample_email_template,
):
    create_service_callback_api(service=sample_email_template.service, url="https://original_url.com", is_suspended=True)

    with patch("app.notifications.callbacks.send_delivery_status_to_service.apply_async") as mock_apply_async:
        _check_and_queue_callback_task(None)
        mock_apply_async.assert_not_called()
