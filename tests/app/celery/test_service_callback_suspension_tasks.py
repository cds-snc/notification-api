from types import SimpleNamespace

from tests.conftest import set_config_values

from app.celery.service_callback_suspension_tasks import send_service_callback_suspension_email


def test_send_service_callback_suspension_email_sends_to_service_owners_and_support_in_production(notify_api, mocker):
    service_id = "service-123"
    mocker.patch(
        "app.celery.service_callback_suspension_tasks.dao_fetch_service_by_id",
        return_value=SimpleNamespace(id=service_id, name="Platform service"),
    )
    mock_send_to_service_users = mocker.patch("app.celery.service_callback_suspension_tasks.send_notification_to_service_users")
    mock_send_to_email_address = mocker.patch("app.celery.service_callback_suspension_tasks.send_notification_to_email_address")

    with set_config_values(
        notify_api,
        {
            "ADMIN_BASE_URL": "https://notification.canada.ca",
            "NOTIFY_ENVIRONMENT": "production",
            "FRESHDESK_SUPPORT_EMAIL_ID": "assistance+notification@cds-snc.ca",
        },
    ):
        send_service_callback_suspension_email(service_id=service_id)

    mock_send_to_service_users.assert_called_once()
    service_users_kwargs = mock_send_to_service_users.call_args.kwargs
    assert service_users_kwargs["service_id"] == service_id
    assert service_users_kwargs["template_id"] == notify_api.config["SERVICE_CALLBACK_SUSPENDED_TEMPLATE_ID"]
    assert "personalisation" in service_users_kwargs
    assert isinstance(service_users_kwargs["personalisation"], dict)
    assert service_users_kwargs["personalisation"]

    mock_send_to_email_address.assert_called_once()
    support_kwargs = mock_send_to_email_address.call_args.kwargs
    assert support_kwargs["email_address"] == "assistance+notification@cds-snc.ca"
    assert support_kwargs["template_id"] == notify_api.config["SERVICE_CALLBACK_SUSPENDED_TEMPLATE_ID"]
    assert "personalisation" in support_kwargs
    assert isinstance(support_kwargs["personalisation"], dict)
    assert support_kwargs["personalisation"]


def test_send_service_callback_suspension_email_does_not_send_support_copy_outside_production(notify_api, mocker):
    service_id = "service-123"
    mocker.patch(
        "app.celery.service_callback_suspension_tasks.dao_fetch_service_by_id",
        return_value=SimpleNamespace(id=service_id, name="Platform service"),
    )
    mock_send_to_service_users = mocker.patch("app.celery.service_callback_suspension_tasks.send_notification_to_service_users")
    mock_send_to_email_address = mocker.patch("app.celery.service_callback_suspension_tasks.send_notification_to_email_address")

    with set_config_values(
        notify_api,
        {
            "ADMIN_BASE_URL": "https://notification.canada.ca",
            "NOTIFY_ENVIRONMENT": "staging",
            "FRESHDESK_SUPPORT_EMAIL_ID": "assistance+notification@cds-snc.ca",
        },
    ):
        send_service_callback_suspension_email(service_id=service_id)

    mock_send_to_service_users.assert_called_once()
    mock_send_to_email_address.assert_not_called()
