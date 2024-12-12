import uuid
from unittest.mock import Mock

import pytest
from notifications_utils import SMS_CHAR_COUNT_LIMIT
from notifications_utils.recipients import InvalidPhoneError

from app.config import QueueNames
from app.dao.service_safelist_dao import dao_add_and_commit_safelisted_contacts
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_NORMAL,
    MOBILE_TYPE,
    SMS_TYPE,
    Notification,
    ServiceSafelist,
)
from app.service.send_notification import send_one_off_notification
from app.v2.errors import (
    BadRequestError,
    LiveServiceTooManyEmailRequestsError,
    LiveServiceTooManySMSRequestsError,
)
from tests.app.db import (
    create_reply_to_email,
    create_service,
    create_service_sms_sender,
    create_template,
    create_user,
)


@pytest.fixture
def persist_mock(mocker):
    noti = Mock(id=uuid.uuid4())
    return mocker.patch("app.service.send_notification.persist_notification", return_value=noti)


@pytest.fixture
def celery_mock(mocker):
    return mocker.patch("app.service.send_notification.send_notification_to_queue")


def test_send_one_off_notification_calls_celery_correctly(persist_mock, celery_mock, notify_db_session):
    service = create_service()
    template = create_template(service=service)

    service = template.service

    post_data = {
        "template_id": str(template.id),
        "to": "6502532222",
        "created_by": str(service.created_by_id),
    }

    resp = send_one_off_notification(service.id, post_data)

    assert resp == {"id": str(persist_mock.return_value.id)}

    celery_mock.assert_called_once_with(
        notification=persist_mock.return_value, research_mode=False, queue=QueueNames.SEND_SMS_MEDIUM
    )


def test_send_one_off_notification_calls_persist_correctly_for_sms(persist_mock, celery_mock, notify_db_session):
    service = create_service()
    template = create_template(
        service=service,
        template_type=SMS_TYPE,
        content="Hello (( Name))\nYour thing is due soon",
    )

    post_data = {
        "template_id": str(template.id),
        "to": "6502532222",
        "personalisation": {"name": "foo"},
        "created_by": str(service.created_by_id),
    }

    send_one_off_notification(service.id, post_data)

    persist_mock.assert_called_once_with(
        template_id=template.id,
        template_version=template.version,
        template_postage=None,
        recipient=post_data["to"],
        service=template.service,
        personalisation={"name": "foo"},
        notification_type=SMS_TYPE,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        created_by_id=str(service.created_by_id),
        reply_to_text="testing",
        reference=None,
    )


def test_send_one_off_notification_calls_persist_correctly_for_email(persist_mock, celery_mock, notify_db_session):
    service = create_service()
    template = create_template(
        service=service,
        template_type=EMAIL_TYPE,
        subject="Test subject",
        content="Hello (( Name))\nYour thing is due soon",
    )

    post_data = {
        "template_id": str(template.id),
        "to": "test@example.com",
        "personalisation": {"name": "foo"},
        "created_by": str(service.created_by_id),
    }

    send_one_off_notification(service.id, post_data)

    persist_mock.assert_called_once_with(
        template_id=template.id,
        template_version=template.version,
        template_postage=None,
        recipient=post_data["to"],
        service=template.service,
        personalisation={"name": "foo"},
        notification_type=EMAIL_TYPE,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        created_by_id=str(service.created_by_id),
        reply_to_text=None,
        reference=None,
    )


def test_send_one_off_notification_honors_research_mode(notify_db_session, persist_mock, celery_mock):
    service = create_service(research_mode=True)
    template = create_template(service=service)

    post_data = {
        "template_id": str(template.id),
        "to": "6502532222",
        "created_by": str(service.created_by_id),
    }

    send_one_off_notification(service.id, post_data)

    assert celery_mock.call_args[1]["research_mode"] is True


@pytest.mark.parametrize(
    "process_type, expected_queue",
    [("priority", QueueNames.SEND_EMAIL_HIGH), ("bulk", QueueNames.SEND_EMAIL_MEDIUM), ("normal", QueueNames.SEND_EMAIL_MEDIUM)],
)
def test_send_one_off_email_notification_honors_process_type(
    notify_db_session, persist_mock, celery_mock, process_type, expected_queue
):
    service = create_service()
    template = create_template(service=service, template_type=EMAIL_TYPE)
    template.process_type = process_type

    post_data = {
        "template_id": str(template.id),
        "to": "test@test.com",
        "created_by": str(service.created_by_id),
    }

    send_one_off_notification(service.id, post_data)

    assert celery_mock.call_args[1]["queue"] == expected_queue


@pytest.mark.parametrize(
    "process_type, expected_queue",
    [("priority", QueueNames.SEND_SMS_HIGH), ("bulk", QueueNames.SEND_SMS_MEDIUM), ("normal", QueueNames.SEND_SMS_MEDIUM)],
)
def test_send_one_off_sms_notification_honors_process_type(
    notify_db_session, persist_mock, celery_mock, process_type, expected_queue
):
    service = create_service()
    template = create_template(service=service, template_type=SMS_TYPE)
    template.process_type = process_type

    post_data = {
        "template_id": str(template.id),
        "to": "6502532222",
        "created_by": str(service.created_by_id),
    }

    send_one_off_notification(service.id, post_data)

    assert celery_mock.call_args[1]["queue"] == expected_queue


def test_send_one_off_notification_raises_if_invalid_recipient(notify_db_session):
    service = create_service()
    template = create_template(service=service)

    post_data = {
        "template_id": str(template.id),
        "to": "not a phone number",
        "created_by": str(service.created_by_id),
    }

    with pytest.raises(InvalidPhoneError):
        send_one_off_notification(service.id, post_data)


@pytest.mark.parametrize(
    "recipient",
    [
        "6502532228",  # not in team or safelist
        "+16502532229",  # in safelist
        "6502532229",  # in safelist in different format
    ],
)
def test_send_one_off_notification_raises_if_cant_send_to_recipient(
    notify_db_session,
    recipient,
):
    service = create_service(restricted=True)
    template = create_template(service=service)
    dao_add_and_commit_safelisted_contacts(
        [
            ServiceSafelist.from_string(service.id, MOBILE_TYPE, "+16502532229"),
        ]
    )

    post_data = {
        "template_id": str(template.id),
        "to": recipient,
        "created_by": str(service.created_by_id),
    }

    with pytest.raises(BadRequestError) as e:
        send_one_off_notification(service.id, post_data)

    assert "service is in trial mode" in e.value.message


def test_send_one_off_notification_raises_if_over_combined_limit(notify_db_session, notify_api, mocker):
    service = create_service(message_limit=0)
    template = create_template(service=service)
    mocker.patch(
        "app.service.send_notification.check_sms_daily_limit",
        side_effect=LiveServiceTooManySMSRequestsError(1),
    )

    post_data = {
        "template_id": str(template.id),
        "to": "6502532222",
        "created_by": str(service.created_by_id),
    }

    with pytest.raises(LiveServiceTooManySMSRequestsError):
        send_one_off_notification(service.id, post_data)


def test_send_one_off_notification_raises_if_over_email_limit(notify_db_session, notify_api, mocker):
    service = create_service(message_limit=0)
    template = create_template(service=service, template_type=EMAIL_TYPE)
    mocker.patch(
        "app.service.send_notification.check_email_daily_limit",
        side_effect=LiveServiceTooManyEmailRequestsError(1),
    )

    post_data = {
        "template_id": str(template.id),
        "to": "6502532222",
        "created_by": str(service.created_by_id),
    }

    with pytest.raises(LiveServiceTooManyEmailRequestsError):
        send_one_off_notification(service.id, post_data)


def test_send_one_off_notification_raises_if_over_sms_daily_limit(notify_db_session, mocker):
    service = create_service(sms_daily_limit=0)
    template = create_template(service=service)
    mocker.patch(
        "app.service.send_notification.check_sms_daily_limit",
        side_effect=LiveServiceTooManySMSRequestsError(1),
    )

    post_data = {
        "template_id": str(template.id),
        "to": "6502532222",
        "created_by": str(service.created_by_id),
    }

    with pytest.raises(LiveServiceTooManySMSRequestsError):
        send_one_off_notification(service.id, post_data)


def test_send_one_off_notification_raises_if_message_too_long(persist_mock, notify_db_session):
    service = create_service()
    template = create_template(service=service, content="Hello (( Name))\nYour thing is due soon")

    post_data = {
        "template_id": str(template.id),
        "to": "6502532222",
        "personalisation": {"name": "🚫" * 700},
        "created_by": str(service.created_by_id),
    }

    with pytest.raises(BadRequestError) as e:
        send_one_off_notification(service.id, post_data)

    assert e.value.message == "Content for template has a character count greater than the limit of {}".format(
        SMS_CHAR_COUNT_LIMIT
    )


def test_send_one_off_notification_fails_if_created_by_other_service(sample_template):
    user_not_in_service = create_user(email="some-other-user@gov.uk")

    post_data = {
        "template_id": str(sample_template.id),
        "to": "6502532222",
        "created_by": str(user_not_in_service.id),
    }

    with pytest.raises(BadRequestError) as e:
        send_one_off_notification(sample_template.service_id, post_data)

    assert e.value.message == 'Can’t create notification - Test User is not part of the "Sample service" service'


def test_send_one_off_notification_should_add_email_reply_to_text_for_notification(sample_email_template, celery_mock):
    reply_to_email = create_reply_to_email(sample_email_template.service, "test@test.com")
    data = {
        "to": "ok@ok.com",
        "template_id": str(sample_email_template.id),
        "sender_id": reply_to_email.id,
        "created_by": str(sample_email_template.service.created_by_id),
    }

    notification_id = send_one_off_notification(service_id=sample_email_template.service.id, post_data=data)
    notification = Notification.query.get(notification_id["id"])
    celery_mock.assert_called_once_with(notification=notification, research_mode=False, queue=QueueNames.SEND_EMAIL_MEDIUM)
    assert notification.reply_to_text == reply_to_email.email_address


def test_send_one_off_sms_notification_should_use_sms_sender_reply_to_text(sample_service, celery_mock):
    template = create_template(service=sample_service, template_type=SMS_TYPE)
    sms_sender = create_service_sms_sender(service=sample_service, sms_sender="6502532222", is_default=False)

    data = {
        "to": "6502532223",
        "template_id": str(template.id),
        "created_by": str(sample_service.created_by_id),
        "sender_id": str(sms_sender.id),
    }

    notification_id = send_one_off_notification(service_id=sample_service.id, post_data=data)
    notification = Notification.query.get(notification_id["id"])
    celery_mock.assert_called_once_with(notification=notification, research_mode=False, queue=QueueNames.SEND_SMS_MEDIUM)

    assert notification.reply_to_text == "+16502532222"


def test_send_one_off_sms_notification_should_use_default_service_reply_to_text(sample_service, celery_mock):
    template = create_template(service=sample_service, template_type=SMS_TYPE)
    sample_service.service_sms_senders[0].is_default = False
    create_service_sms_sender(service=sample_service, sms_sender="6502532222", is_default=True)

    data = {
        "to": "6502532223",
        "template_id": str(template.id),
        "created_by": str(sample_service.created_by_id),
    }

    notification_id = send_one_off_notification(service_id=sample_service.id, post_data=data)
    notification = Notification.query.get(notification_id["id"])
    celery_mock.assert_called_once_with(notification=notification, research_mode=False, queue=QueueNames.SEND_SMS_MEDIUM)

    assert notification.reply_to_text == "+16502532222"


def test_send_one_off_notification_should_throw_exception_if_reply_to_id_doesnot_exist(
    sample_email_template,
):
    data = {
        "to": "ok@ok.com",
        "template_id": str(sample_email_template.id),
        "sender_id": str(uuid.uuid4()),
        "created_by": str(sample_email_template.service.created_by_id),
    }

    with pytest.raises(expected_exception=BadRequestError) as e:
        send_one_off_notification(service_id=sample_email_template.service.id, post_data=data)
    assert e.value.message == "Reply to email address not found"


def test_send_one_off_notification_should_throw_exception_if_sms_sender_id_doesnot_exist(
    sample_template,
):
    data = {
        "to": "6502532222",
        "template_id": str(sample_template.id),
        "sender_id": str(uuid.uuid4()),
        "created_by": str(sample_template.service.created_by_id),
    }

    with pytest.raises(expected_exception=BadRequestError) as e:
        send_one_off_notification(service_id=sample_template.service.id, post_data=data)
    assert e.value.message == "SMS sender not found"
