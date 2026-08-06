from types import SimpleNamespace

import pytest
from tests.conftest import set_config_values

from app.celery.bounce_rate_tasks import send_bounce_rate_suspension_email, send_bounce_rate_warning_email


@pytest.mark.parametrize(
    "task_function, template_id_key, should_send_support_copy",
    [
        (send_bounce_rate_suspension_email, "SERVICE_BOUNCE_RATE_SUSPENDED_TEMPLATE_ID", True),
        (send_bounce_rate_warning_email, "SERVICE_SUSPENDED_WARNING_TEMPLATE_ID", False),
    ],
)
def test_bounce_rate_tasks_send_to_service_owners(
    notify_api,
    mocker,
    task_function,
    template_id_key,
    should_send_support_copy,
):
    service_id = "service-123"
    bounce_rate = 0.056789

    mock_service = mocker.patch("app.celery.bounce_rate_tasks.Service")
    mock_service.query.get.return_value = SimpleNamespace(name="Platform service")
    mock_send_to_service_users = mocker.patch("app.celery.bounce_rate_tasks.send_notification_to_service_users")
    mock_send_to_email_address = mocker.patch("app.celery.bounce_rate_tasks.send_notification_to_email_address")

    with set_config_values(
        notify_api,
        {
            "ADMIN_BASE_URL": "https://admin.notification.canada.ca",
            "FRESHDESK_SUPPORT_EMAIL_ID": "assistance+notification@cds-snc.ca",
        },
    ):
        task_function(service_id=service_id, bounce_rate=bounce_rate)

    expected_personalisation = {
        "service_name": "Platform service",
        "bounce_rate": 5.68,
        "failed_notifications_url_en": f"https://admin.notification.canada.ca/services/{service_id}/notifications/email?status=failed",
        "failed_notifications_url_fr": f"https://admin.notification.canada.ca/services/{service_id}/notifications/email?status=failed&lang=fr",
        "service_dashboard_url_en": f"https://admin.notification.canada.ca/services/{service_id}",
        "service_dashboard_url_fr": f"https://admin.notification.canada.ca/services/{service_id}?lang=fr",
    }

    mock_service.query.get.assert_called_once_with(service_id)
    mock_send_to_service_users.assert_called_once_with(
        service_id=service_id,
        template_id=notify_api.config[template_id_key],
        personalisation=expected_personalisation,
        include_user_fields=["name"],
    )
    if should_send_support_copy:
        mock_send_to_email_address.assert_called_once_with(
            email_address="assistance+notification@cds-snc.ca",
            template_id=notify_api.config[template_id_key],
            personalisation={**expected_personalisation, "name": "Freshdesk support"},
        )
    else:
        mock_send_to_email_address.assert_not_called()
