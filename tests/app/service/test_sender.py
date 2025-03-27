import pytest
from flask import current_app
from sqlalchemy import select

from app.constants import EMAIL_TYPE, SMS_TYPE
from app.dao.services_dao import dao_add_user_to_service
from app.models import Notification, User
from app.service.sender import send_notification_to_service_users


@pytest.mark.parametrize('notification_type', [EMAIL_TYPE, SMS_TYPE])
def test_send_notification_to_service_users_persists_notifications_correctly(
    notify_db_session,
    notification_type,
    sample_service,
    sample_template,
    mocker,
):
    service = sample_service()
    sender_service = sample_service()
    user = service.users[0]

    mocker.patch('app.service.sender.send_notification_to_queue')
    mocker.patch('app.service.sender.current_app.config', {'NOTIFY_SERVICE_ID': str(sender_service.id)})

    template = sample_template(service=service, user=user, template_type=notification_type)
    send_notification_to_service_users(service_id=service.id, template_id=template.id)
    to = user.email_address if notification_type == EMAIL_TYPE else user.mobile_number

    stmt = select(Notification).where(Notification.service_id == sender_service.id).where(Notification.to == to)
    notification = notify_db_session.session.scalars(stmt).one()

    assert notification.to == to
    assert str(notification.service_id) == current_app.config['NOTIFY_SERVICE_ID']
    assert notification.template.id == template.id
    assert notification.template.template_type == notification_type
    assert notification.notification_type == notification_type
    assert notification.reply_to_text is None


def test_send_notification_to_service_users_sends_to_queue(
    notify_api,
    sample_service,
    sample_template,
    mocker,
):
    sender_service = sample_service()
    mocker.patch(
        'app.service.sender.current_app.config',
        {'NOTIFY_SERVICE_ID': str(sender_service.id), 'FROM_NUMBER': '+1234567890'},
    )

    send_mock = mocker.patch('app.service.sender.send_notification_to_queue')

    service = sample_service()
    service.users[0]
    template = sample_template(service=service, template_type=EMAIL_TYPE)
    send_notification_to_service_users(service_id=service.id, template_id=template.id)

    assert send_mock.called
    assert send_mock.call_count == 1


def test_send_notification_to_service_users_includes_user_fields_in_personalisation(
    sample_service,
    sample_template,
    mocker,
):
    sender_service = sample_service()
    mocker.patch(
        'app.service.sender.current_app.config',
        {'NOTIFY_SERVICE_ID': str(sender_service.id), 'FROM_NUMBER': '+1234567890'},
    )
    persist_mock = mocker.patch('app.service.sender.persist_notification')
    mocker.patch('app.service.sender.send_notification_to_queue')

    service = sample_service()
    user = service.users[0]

    template = sample_template(service=service, template_type=EMAIL_TYPE)
    send_notification_to_service_users(
        service_id=service.id, template_id=template.id, include_user_fields=['name', 'email_address', 'state']
    )

    persist_call = persist_mock.call_args_list[0][1]

    assert len(persist_mock.call_args_list) == 1
    assert persist_call['personalisation'] == {
        'name': user.name,
        'email_address': user.email_address,
        'state': user.state,
    }

    # Teardown not necessary - Notification not persisted


def test_send_notification_to_service_users_sends_to_active_users_only(
    notify_api,
    sample_service,
    sample_template,
    sample_user,
    mocker,
):
    sender_service = sample_service()
    mocker.patch(
        'app.service.sender.current_app.config',
        {'NOTIFY_SERVICE_ID': str(sender_service.id), 'FROM_NUMBER': '+1234567890'},
    )
    mocker.patch('app.service.sender.send_notification_to_queue')
    mock_persist = mocker.patch('app.service.sender.persist_notification')
    mock_enqueue = mocker.patch('app.service.sender.send_notification_to_queue')

    # User and service setup
    total_users = 12
    first_active_user: User = sample_user()
    second_active_user: User = sample_user()
    pending_user = sample_user(state='pending')
    service = sample_service(user=first_active_user)
    dao_add_user_to_service(service, second_active_user)
    # add more users
    extra_user_emails = []
    for _ in range(total_users - 2):
        extra_user: User = sample_user()
        extra_user_emails.append(extra_user.email_address)
        dao_add_user_to_service(service, extra_user)
    dao_add_user_to_service(service, pending_user)

    # Sending the notifications
    template = sample_template(service=service, template_type=EMAIL_TYPE)
    # Cleaned by sample_template
    send_notification_to_service_users(service_id=service.id, template_id=template.id)

    # persist_notification and send_notification_to_queue are super slow and they are tested elsewhere
    assert mock_persist.call_count == mock_enqueue.call_count == total_users
