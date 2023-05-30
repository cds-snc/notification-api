from datetime import datetime

from app import DATETIME_FORMAT, signer_complaint, signer_delivery_status
from app.notifications.callbacks import (
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
