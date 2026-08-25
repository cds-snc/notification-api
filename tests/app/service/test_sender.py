from types import SimpleNamespace

import pytest
from flask import current_app

from app.config import QueueNames
from app.dao.services_dao import dao_add_user_to_service
from app.models import EMAIL_TYPE, KEY_TYPE_NORMAL, SMS_TYPE, Notification
from app.service.sender import send_notification_to_email_address, send_notification_to_service_users
from tests.app.conftest import create_sample_service
from tests.app.conftest import notify_service as create_notify_service
from tests.app.db import create_template, create_user


@pytest.mark.parametrize("notification_type", [EMAIL_TYPE, SMS_TYPE])
def test_send_notification_to_service_users_persists_notifications_correctly(
    notify_db, notify_db_session, notification_type, sample_user, mocker
):
    mocker.patch("app.service.sender.send_notification_to_queue")

    notify_service, user = create_notify_service(notify_db, notify_db_session)
    service = create_sample_service(notify_db, notify_db_session, user=sample_user)
    template = create_template(service, template_type=notification_type)
    send_notification_to_service_users(service_id=service.id, template_id=template.id)
    to = sample_user.email_address if notification_type == EMAIL_TYPE else sample_user.mobile_number

    notification = Notification.query.one()

    assert Notification.query.count() == 1
    assert notification.to == to
    assert str(notification.service_id) == current_app.config["NOTIFY_SERVICE_ID"]
    assert notification.template.id == template.id
    assert notification.template.template_type == notification_type
    assert notification.notification_type == notification_type
    assert notification.reply_to_text == notify_service.get_default_reply_to_email_address()


def test_send_notification_to_service_users_sends_to_queue(notify_db, notify_db_session, sample_user, mocker):
    send_mock = mocker.patch("app.service.sender.send_notification_to_queue")

    create_notify_service(notify_db, notify_db_session)
    service = create_sample_service(notify_db, notify_db_session, user=sample_user)
    template = create_template(service, template_type=EMAIL_TYPE)
    send_notification_to_service_users(service_id=service.id, template_id=template.id)

    assert send_mock.called
    assert send_mock.call_count == 1


def test_send_notification_to_service_users_includes_user_fields_in_personalisation(
    notify_db, notify_db_session, sample_user, mocker
):
    persist_mock = mocker.patch("app.service.sender.persist_notification")
    mocker.patch("app.service.sender.send_notification_to_queue")

    create_notify_service(notify_db, notify_db_session)
    service = create_sample_service(notify_db, notify_db_session, user=sample_user)
    template = create_template(service, template_type=EMAIL_TYPE)
    send_notification_to_service_users(
        service_id=service.id,
        template_id=template.id,
        include_user_fields=["name", "email_address", "state"],
    )

    persist_call = persist_mock.call_args_list[0][1]

    assert len(persist_mock.call_args_list) == 1
    assert persist_call["personalisation"] == {
        "name": sample_user.name,
        "email_address": sample_user.email_address,
        "state": sample_user.state,
    }


def test_send_notification_to_service_users_sends_to_active_users_only(notify_db, notify_db_session, mocker):
    mocker.patch("app.service.sender.send_notification_to_queue")

    create_notify_service(notify_db, notify_db_session)

    first_active_user = create_user(email="foo@bar.com", state="active")
    second_active_user = create_user(email="foo1@bar.com", state="active")
    pending_user = create_user(email="foo2@bar.com", state="pending")
    service = create_sample_service(notify_db, notify_db_session, user=first_active_user)
    dao_add_user_to_service(service, second_active_user)
    dao_add_user_to_service(service, pending_user)
    template = create_template(service, template_type=EMAIL_TYPE)

    send_notification_to_service_users(service_id=service.id, template_id=template.id)
    notifications = Notification.query.all()
    notifications_recipients = [notification.to for notification in notifications]

    assert Notification.query.count() == 2
    assert pending_user.email_address not in notifications_recipients
    assert first_active_user.email_address in notifications_recipients
    assert second_active_user.email_address in notifications_recipients


def test_send_notification_to_email_address_persists_and_queues_notification(notify_api, mocker):
    fake_template = SimpleNamespace(id="template-123", version=4, template_type=EMAIL_TYPE)
    fake_notify_service = SimpleNamespace(get_default_reply_to_email_address=lambda: "reply-to@notification.canada.ca")
    saved_notification = object()

    mock_get_template = mocker.patch("app.service.sender.dao_get_template_by_id", return_value=fake_template)
    mock_get_service = mocker.patch("app.service.sender.dao_fetch_service_by_id", return_value=fake_notify_service)
    mock_persist_notification = mocker.patch("app.service.sender.persist_notification", return_value=saved_notification)
    mock_send_to_queue = mocker.patch("app.service.sender.send_notification_to_queue")

    personalisation = {"service_name": "Platform service", "name": "Freshdesk support"}
    recipient = notify_api.config["FRESHDESK_SUPPORT_EMAIL_ID"]

    send_notification_to_email_address(
        email_address=recipient,
        template_id="template-123",
        personalisation=personalisation,
    )

    mock_get_template.assert_called_once_with("template-123")
    mock_get_service.assert_called_once_with(current_app.config["NOTIFY_SERVICE_ID"])
    mock_persist_notification.assert_called_once_with(
        template_id=fake_template.id,
        template_version=fake_template.version,
        recipient=recipient,
        service=fake_notify_service,
        personalisation=personalisation,
        notification_type=fake_template.template_type,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        reply_to_text="reply-to@notification.canada.ca",
    )
    mock_send_to_queue.assert_called_once_with(saved_notification, False, queue=QueueNames.NOTIFY)
