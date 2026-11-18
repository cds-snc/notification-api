from flask import current_app

from app import notify_celery
from app.dao.services_dao import dao_fetch_service_by_id
from app.service.sender import send_notification_to_email_address, send_notification_to_service_users


def _build_callback_suspension_personalisation(service_id: str, service_name: str) -> dict:
    admin_base_url = current_app.config["ADMIN_BASE_URL"].rstrip("/")
    return {
        "service_name": service_name,
        "service_id": service_id,
        "service_callback_url_en": f"{admin_base_url}/services/{service_id}/api/callbacks/delivery-status-callback",
        "service_callback_url_fr": f"{admin_base_url}/services/{service_id}/api/callbacks/delivery-status-callback?lang=fr",
    }


@notify_celery.task(name="send-service-callback-suspension-email")
def send_service_callback_suspension_email(service_id: str):
    service = dao_fetch_service_by_id(service_id)
    personalisation = _build_callback_suspension_personalisation(service_id=str(service.id), service_name=service.name)

    send_notification_to_service_users(
        service_id=service_id,
        template_id=current_app.config["SERVICE_CALLBACK_SUSPENDED_TEMPLATE_ID"],
        personalisation=personalisation,
    )

    # Keep support-copy behavior production-only to avoid noise in test/sandbox environments.
    if current_app.config["NOTIFY_ENVIRONMENT"] == "production":
        send_notification_to_email_address(
            email_address=current_app.config["FRESHDESK_SUPPORT_EMAIL_ID"],
            template_id=current_app.config["SERVICE_CALLBACK_SUSPENDED_TEMPLATE_ID"],
            personalisation={**personalisation, "name": "Freshdesk support"},
        )
