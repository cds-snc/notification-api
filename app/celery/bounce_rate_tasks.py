from flask import current_app

from app import notify_celery
from app.models import Service
from app.service.sender import send_notification_to_email_address, send_notification_to_service_users


def _build_bounce_rate_personalisation(service_name: str, service_id: str, bounce_rate: float) -> dict:
    return {
        "service_name": service_name,
        "bounce_rate": round(bounce_rate * 100, 2),
        "failed_notifications_url_en": f"{current_app.config['ADMIN_BASE_URL']}/services/{service_id}/notifications/email?status=failed",
        "failed_notifications_url_fr": f"{current_app.config['ADMIN_BASE_URL']}/services/{service_id}/notifications/email?status=failed&lang=fr",
        "service_dashboard_url_en": f"{current_app.config['ADMIN_BASE_URL']}/services/{service_id}",
        "service_dashboard_url_fr": f"{current_app.config['ADMIN_BASE_URL']}/services/{service_id}?lang=fr",
    }


def _send_bounce_rate_email(
    service_id: str,
    bounce_rate: float,
    template_id: str,
    send_support_copy: bool = False,
):
    service = Service.query.get(service_id)
    personalisation = _build_bounce_rate_personalisation(
        service_name=service.name, service_id=service_id, bounce_rate=bounce_rate
    )

    send_notification_to_service_users(
        service_id=service_id,
        template_id=template_id,
        personalisation=personalisation.copy(),
        include_user_fields=["name"],
    )

    if send_support_copy and current_app.config["NOTIFY_ENVIRONMENT"] == "production":
        send_notification_to_email_address(
            email_address=current_app.config["FRESHDESK_SUPPORT_EMAIL_ID"],
            template_id=template_id,
            personalisation={**personalisation, "name": "Freshdesk support"},
        )


@notify_celery.task(name="send-bounce-rate-suspension-email")
def send_bounce_rate_suspension_email(service_id: str, bounce_rate: float):
    _send_bounce_rate_email(
        service_id=service_id,
        bounce_rate=bounce_rate,
        template_id=current_app.config["SERVICE_BOUNCE_RATE_SUSPENDED_TEMPLATE_ID"],
        send_support_copy=True,
    )


@notify_celery.task(name="send-bounce-rate-warning-email")
def send_bounce_rate_warning_email(service_id: str, bounce_rate: float):
    _send_bounce_rate_email(
        service_id=service_id,
        bounce_rate=bounce_rate,
        template_id=current_app.config["SERVICE_SUSPENDED_WARNING_TEMPLATE_ID"],
    )
