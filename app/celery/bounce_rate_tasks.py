from flask import current_app

from app import notify_celery
from app.models import Service
from app.service.sender import send_notification_to_service_users


@notify_celery.task(name="send-bounce-rate-suspension-email")
def send_bounce_rate_suspension_email(service_id: str, bounce_rate: float):
    service = Service.query.get(service_id)
    send_notification_to_service_users(
        service_id=service_id,
        template_id=current_app.config["SERVICE_BOUNCE_RATE_SUSPENDED_TEMPLATE_ID"],
        personalisation={
            "service_name": service.name,
            "bounce_rate": round(bounce_rate * 100, 2),
            "failed_notifications_url_en": f"{current_app.config['ADMIN_BASE_URL']}/services/{service_id}/problem-emails",
            "failed_notifications_url_fr": f"{current_app.config['ADMIN_BASE_URL']}/services/{service_id}/problem-emails?lang=fr",
            "service_dashboard_url": f"{current_app.config['ADMIN_BASE_URL']}/services/{service_id}",
        },
        include_user_fields=["name"],
    )


@notify_celery.task(name="send-bounce-rate-warning-email")
def send_bounce_rate_warning_email(service_id: str, bounce_rate: float):
    service = Service.query.get(service_id)
    send_notification_to_service_users(
        service_id=service_id,
        template_id=current_app.config["SERVICE_SUSPENDED_WARNING_TEMPLATE_ID"],
        personalisation={
            "service_name": service.name,
            "bounce_rate": round(bounce_rate * 100, 2),
            "failed_notifications_url_en": f"{current_app.config['ADMIN_BASE_URL']}/services/{service_id}/problem-emails",
            "failed_notifications_url_fr": f"{current_app.config['ADMIN_BASE_URL']}/services/{service_id}/problem-emails?lang=fr",
            "service_dashboard_url_en": f"{current_app.config['ADMIN_BASE_URL']}/services/{service_id}",
            "service_dashboard_url_fr": f"{current_app.config['ADMIN_BASE_URL']}/services/{service_id}?lang=fr",
        },
        include_user_fields=["name"],
    )
