import uuid
from unittest.mock import Mock

import pytest
from freezegun import freeze_time
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
    ScheduledNotification,
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


def test_send_one_off_notification_calls_celery_correctly(persist_mock, celery_mock, notify_db_session, mocker):
    service = create_service()
    template = create_template(service=service)

    service = template.service

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

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


def test_send_one_off_notification_calls_persist_correctly_for_sms(persist_mock, celery_mock, notify_db_session, mocker):
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
    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

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
        billable_units=1,
    )


def test_send_one_off_notification_calls_persist_correctly_for_email(persist_mock, celery_mock, notify_db_session, mocker):
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

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

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
        billable_units=None,
    )


def test_send_one_off_notification_honors_research_mode(notify_db_session, persist_mock, celery_mock, mocker):
    service = create_service(research_mode=True)
    template = create_template(service=service)

    post_data = {
        "template_id": str(template.id),
        "to": "6502532222",
        "created_by": str(service.created_by_id),
    }

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

    send_one_off_notification(service.id, post_data)

    assert celery_mock.call_args[1]["research_mode"] is True


@pytest.mark.parametrize(
    "process_type, expected_queue",
    [("priority", QueueNames.SEND_EMAIL_HIGH), ("bulk", QueueNames.SEND_EMAIL_MEDIUM), ("normal", QueueNames.SEND_EMAIL_MEDIUM)],
)
def test_send_one_off_email_notification_honors_process_type(
    notify_db_session, persist_mock, celery_mock, process_type, expected_queue, mocker
):
    service = create_service()
    template = create_template(service=service, template_type=EMAIL_TYPE)
    template.process_type = process_type

    post_data = {
        "template_id": str(template.id),
        "to": "test@test.com",
        "created_by": str(service.created_by_id),
    }

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

    send_one_off_notification(service.id, post_data)

    assert celery_mock.call_args[1]["queue"] == expected_queue


@pytest.mark.parametrize(
    "process_type, expected_queue",
    [("priority", QueueNames.SEND_SMS_HIGH), ("bulk", QueueNames.SEND_SMS_MEDIUM), ("normal", QueueNames.SEND_SMS_MEDIUM)],
)
def test_send_one_off_sms_notification_honors_process_type(
    notify_db_session, persist_mock, celery_mock, process_type, expected_queue, mocker
):
    service = create_service()
    template = create_template(service=service, template_type=SMS_TYPE)
    template.process_type = process_type

    post_data = {
        "template_id": str(template.id),
        "to": "6502532222",
        "created_by": str(service.created_by_id),
    }

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

    send_one_off_notification(service.id, post_data)

    assert celery_mock.call_args[1]["queue"] == expected_queue


def test_send_one_off_notification_raises_if_invalid_recipient(notify_db_session, mocker):
    service = create_service()
    template = create_template(service=service)

    post_data = {
        "template_id": str(template.id),
        "to": "not a phone number",
        "created_by": str(service.created_by_id),
    }

    with pytest.raises(InvalidPhoneError):
        mocker.patch(
            "app.notifications.validators.get_annual_limit_notifications_v2",
            return_value={
                "total_email_fiscal_year_to_yesterday": 0,
                "total_sms_fiscal_year_to_yesterday": 0,
            },
        )
        send_one_off_notification(service.id, post_data)


@pytest.mark.parametrize(
    "recipient",
    [
        "6502532228",  # not in team or safelist
        "+16502532229",  # in safelist
        "6502532229",  # in safelist in different format
    ],
)
def test_send_one_off_notification_raises_if_cant_send_to_recipient(notify_db_session, recipient, mocker):
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
        mocker.patch(
            "app.notifications.validators.get_annual_limit_notifications_v2",
            return_value={
                "total_email_fiscal_year_to_yesterday": 0,
                "total_sms_fiscal_year_to_yesterday": 0,
            },
        )

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
        mocker.patch(
            "app.notifications.validators.get_annual_limit_notifications_v2",
            return_value={
                "total_email_fiscal_year_to_yesterday": 0,
                "total_sms_fiscal_year_to_yesterday": 0,
            },
        )

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

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

    with pytest.raises(LiveServiceTooManyEmailRequestsError):
        send_one_off_notification(service.id, post_data)


def test_send_one_off_notification_raises_if_over_sms_daily_limit(notify_db_session, mocker):
    service = create_service(sms_daily_limit=0)
    template = create_template(service=service)
    mocker.patch(
        "app.service.send_notification.check_sms_daily_limit",
        side_effect=LiveServiceTooManySMSRequestsError(1),
    )
    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

    post_data = {
        "template_id": str(template.id),
        "to": "6502532222",
        "created_by": str(service.created_by_id),
    }

    with pytest.raises(LiveServiceTooManySMSRequestsError):
        send_one_off_notification(service.id, post_data)


def test_send_one_off_notification_raises_if_message_too_long(persist_mock, notify_db_session, mocker):
    service = create_service()
    template = create_template(service=service, content="Hello (( Name))\nYour thing is due soon")

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

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


def test_send_one_off_notification_fails_if_created_by_other_service(sample_template, mocker):
    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )
    user_not_in_service = create_user(email="some-other-user@gov.uk")

    post_data = {
        "template_id": str(sample_template.id),
        "to": "6502532222",
        "created_by": str(user_not_in_service.id),
    }

    with pytest.raises(BadRequestError) as e:
        send_one_off_notification(sample_template.service_id, post_data)

    assert e.value.message == 'Can’t create notification - Test User is not part of the "Sample service" service'


def test_send_one_off_notification_should_add_email_reply_to_text_for_notification(sample_email_template, celery_mock, mocker):
    reply_to_email = create_reply_to_email(sample_email_template.service, "test@test.com")
    data = {
        "to": "ok@ok.com",
        "template_id": str(sample_email_template.id),
        "sender_id": reply_to_email.id,
        "created_by": str(sample_email_template.service.created_by_id),
    }

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

    notification_id = send_one_off_notification(service_id=sample_email_template.service.id, post_data=data)
    notification = Notification.query.get(notification_id["id"])
    celery_mock.assert_called_once_with(notification=notification, research_mode=False, queue=QueueNames.SEND_EMAIL_MEDIUM)
    assert notification.reply_to_text == reply_to_email.email_address


def test_send_one_off_sms_notification_should_use_sms_sender_reply_to_text(sample_service, celery_mock, mocker):
    template = create_template(service=sample_service, template_type=SMS_TYPE)
    sms_sender = create_service_sms_sender(service=sample_service, sms_sender="6502532222", is_default=False)

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

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


def test_send_one_off_sms_notification_should_use_default_service_reply_to_text(sample_service, celery_mock, mocker):
    template = create_template(service=sample_service, template_type=SMS_TYPE)
    sample_service.service_sms_senders[0].is_default = False
    create_service_sms_sender(service=sample_service, sms_sender="6502532222", is_default=True)

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

    data = {
        "to": "6502532223",
        "template_id": str(template.id),
        "created_by": str(sample_service.created_by_id),
    }

    notification_id = send_one_off_notification(service_id=sample_service.id, post_data=data)
    notification = Notification.query.get(notification_id["id"])
    celery_mock.assert_called_once_with(notification=notification, research_mode=False, queue=QueueNames.SEND_SMS_MEDIUM)

    assert notification.reply_to_text == "+16502532222"


def test_send_one_off_notification_should_throw_exception_if_reply_to_id_doesnot_exist(sample_email_template, mocker):
    data = {
        "to": "ok@ok.com",
        "template_id": str(sample_email_template.id),
        "sender_id": str(uuid.uuid4()),
        "created_by": str(sample_email_template.service.created_by_id),
    }

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

    with pytest.raises(expected_exception=BadRequestError) as e:
        send_one_off_notification(service_id=sample_email_template.service.id, post_data=data)
    assert e.value.message == "Reply to email address not found"


def test_send_one_off_notification_should_throw_exception_if_sms_sender_id_doesnot_exist(sample_template, mocker):
    data = {
        "to": "6502532222",
        "template_id": str(sample_template.id),
        "sender_id": str(uuid.uuid4()),
        "created_by": str(sample_template.service.created_by_id),
    }

    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )

    with pytest.raises(expected_exception=BadRequestError) as e:
        send_one_off_notification(service_id=sample_template.service.id, post_data=data)
    assert e.value.message == "SMS sender not found"


class TestBillableUnitsInSendOneOffNotification:
    """Tests for billable_units in send_one_off_notification"""

    def test_send_one_off_sms_uses_billable_units(self, notify_db_session, mocker):
        """Test that send_one_off_notification uses billable_units from persist_notification"""
        service = create_service()
        # Create template with long content to ensure multiple fragments
        template = create_template(
            service=service,
            template_type=SMS_TYPE,
            content="a" * 200,  # Long message -> 2 fragments
        )

        # Mock persist_notification to return a notification with billable_units set
        mock_notification = Mock(id=uuid.uuid4(), billable_units=2)
        mocker.patch("app.service.send_notification.persist_notification", return_value=mock_notification)
        mocker.patch("app.service.send_notification.send_notification_to_queue")
        mock_increment = mocker.patch("app.service.send_notification.increment_sms_daily_count_send_warnings_if_needed")
        mocker.patch(
            "app.notifications.validators.get_annual_limit_notifications_v2",
            return_value={
                "total_email_fiscal_year_to_yesterday": 0,
                "total_sms_fiscal_year_to_yesterday": 0,
            },
        )

        post_data = {
            "template_id": str(template.id),
            "to": "6502532222",
            "created_by": str(service.created_by_id),
        }

        send_one_off_notification(service.id, post_data)

        # Verify increment was called with billable_units=2
        mock_increment.assert_called_once_with(service, 2)

    def test_send_one_off_sms_test_notification_does_not_increment(self, notify_db_session, mocker):
        """Test that test notifications don't increment daily count even with billable_units"""
        service = create_service()
        template = create_template(
            service=service,
            template_type=SMS_TYPE,
            content="a" * 200,
        )

        mock_notification = Mock(id=uuid.uuid4(), billable_units=2)
        mocker.patch("app.service.send_notification.persist_notification", return_value=mock_notification)
        mocker.patch("app.service.send_notification.send_notification_to_queue")
        mock_increment = mocker.patch("app.service.send_notification.increment_sms_daily_count_send_warnings_if_needed")
        mocker.patch("app.service.send_notification.simulated_recipient", return_value=True)
        mocker.patch(
            "app.notifications.validators.get_annual_limit_notifications_v2",
            return_value={
                "total_email_fiscal_year_to_yesterday": 0,
                "total_sms_fiscal_year_to_yesterday": 0,
            },
        )

        post_data = {
            "template_id": str(template.id),
            "to": "6132532222",  # Simulated/test number
            "created_by": str(service.created_by_id),
        }

        send_one_off_notification(service.id, post_data)

        # Test notifications should not increment daily count
        mock_increment.assert_not_called()

    def test_send_one_off_email_does_not_use_billable_units(self, notify_db_session, mocker):
        """Test that email notifications don't use billable_units"""
        service = create_service()
        template = create_template(
            service=service,
            template_type=EMAIL_TYPE,
            subject="Test",
            content="Email content",
        )

        mock_notification = Mock(id=uuid.uuid4(), billable_units=None)
        mocker.patch("app.service.send_notification.persist_notification", return_value=mock_notification)
        mocker.patch("app.service.send_notification.send_notification_to_queue")
        mock_increment = mocker.patch("app.service.send_notification.increment_email_daily_count_send_warnings_if_needed")
        mocker.patch(
            "app.notifications.validators.get_annual_limit_notifications_v2",
            return_value={
                "total_email_fiscal_year_to_yesterday": 0,
                "total_sms_fiscal_year_to_yesterday": 0,
            },
        )

        post_data = {
            "template_id": str(template.id),
            "to": "test@example.com",
            "created_by": str(service.created_by_id),
        }

        send_one_off_notification(service.id, post_data)

        # Email increment always uses 1, never billable_units
        mock_increment.assert_called_once_with(service, 1)


@pytest.fixture
def mock_annual_limits(mocker):
    mocker.patch(
        "app.notifications.validators.get_annual_limit_notifications_v2",
        return_value={
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
        },
    )


class TestScheduledOneOffNotification:
    @freeze_time("2017-05-01 14:00:00")
    @pytest.mark.parametrize("template_type, to", [(SMS_TYPE, "6502532222"), (EMAIL_TYPE, "ok@ok.com")])
    def test_stores_scheduled_notification_and_does_not_send_it(
        self, notify_db_session, celery_mock, mock_annual_limits, template_type, to
    ):
        service = create_service()
        template = create_template(service=service, template_type=template_type, content="Hello ((name))")

        resp = send_one_off_notification(
            service.id,
            {
                "template_id": str(template.id),
                "to": to,
                "personalisation": {"name": "Jo"},
                "created_by": str(service.created_by_id),
                "scheduled_for": "2017-05-02 10:00",
            },
        )

        assert not celery_mock.called
        assert Notification.query.count() == 0
        scheduled = ScheduledNotification.query.one()
        assert resp == {"id": str(scheduled.notification_id)}
        assert scheduled.service_id == service.id
        assert scheduled.template_id == template.id
        assert scheduled.to == to
        assert scheduled.personalisation == {"name": "Jo"}
        assert scheduled.api_key_id is None
        assert scheduled.key_type == KEY_TYPE_NORMAL
        assert scheduled.created_by_id == service.created_by_id
        assert scheduled.scheduled_for.isoformat() == "2017-05-02T10:00:00"

    @freeze_time("2017-05-01 14:00:00")
    @pytest.mark.parametrize("scheduled_for, counted_today", [("2017-05-01 20:00", True), ("2017-05-02 10:00", False)])
    def test_only_counts_towards_todays_limit_if_scheduled_for_today(
        self, notify_db_session, celery_mock, mock_annual_limits, mocker, scheduled_for, counted_today
    ):
        increment_mock = mocker.patch("app.service.send_notification.increment_sms_daily_count_send_warnings_if_needed")
        service = create_service()
        template = create_template(service=service)

        send_one_off_notification(
            service.id,
            {
                "template_id": str(template.id),
                "to": "6502532222",
                "created_by": str(service.created_by_id),
                "scheduled_for": scheduled_for,
            },
        )

        assert increment_mock.called is counted_today

    @freeze_time("2017-05-01 14:00:00")
    @pytest.mark.parametrize("template_type, to", [(SMS_TYPE, "6502532222"), (EMAIL_TYPE, "ok@ok.com")])
    def test_can_schedule_for_a_later_day_when_todays_daily_limit_is_used_up(
        self, notify_db_session, celery_mock, mock_annual_limits, mocker, template_type, to
    ):
        service = create_service(message_limit=10, sms_daily_limit=10)
        template = create_template(service=service, template_type=template_type)
        mocker.patch("app.notifications.validators.fetch_todays_email_count", return_value=10)
        mocker.patch("app.notifications.validators.fetch_todays_requested_sms_billable_units_count", return_value=10)

        send_one_off_notification(
            service.id,
            {
                "template_id": str(template.id),
                "to": to,
                "created_by": str(service.created_by_id),
                "scheduled_for": "2017-05-02 10:00",
            },
        )

        assert ScheduledNotification.query.count() == 1

    @freeze_time("2017-05-01 14:00:00")
    @pytest.mark.parametrize(
        "template_type, to, expected_error",
        [
            (SMS_TYPE, "6502532222", LiveServiceTooManySMSRequestsError),
            (EMAIL_TYPE, "ok@ok.com", LiveServiceTooManyEmailRequestsError),
        ],
    )
    @pytest.mark.parametrize(
        "scheduled_for, todays_count, scheduled_days_count",
        [
            # later today, and today's limit is used up
            ("2017-05-01 20:00", 10, 0),
            # a later day, and that day's limit is used up
            ("2017-05-02 10:00", 0, 10),
        ],
        ids=["later_today", "later_day"],
    )
    def test_raises_if_daily_limit_of_scheduled_day_is_used_up(
        self,
        notify_db_session,
        celery_mock,
        mock_annual_limits,
        mocker,
        template_type,
        to,
        expected_error,
        scheduled_for,
        todays_count,
        scheduled_days_count,
    ):
        service = create_service(message_limit=10, sms_daily_limit=10)
        template = create_template(service=service, template_type=template_type)
        mocker.patch("app.notifications.validators.fetch_todays_email_count", return_value=todays_count)
        mocker.patch("app.notifications.validators.fetch_todays_requested_sms_billable_units_count", return_value=todays_count)
        mocker.patch("app.notifications.validators.fetch_scheduled_email_count_for_day", return_value=scheduled_days_count)
        mocker.patch("app.notifications.validators.fetch_scheduled_sms_billable_units_for_day", return_value=scheduled_days_count)

        with pytest.raises(expected_error):
            send_one_off_notification(
                service.id,
                {
                    "template_id": str(template.id),
                    "to": to,
                    "created_by": str(service.created_by_id),
                    "scheduled_for": scheduled_for,
                },
            )

        assert ScheduledNotification.query.count() == 0

    @freeze_time("2017-05-01 14:00:00")
    @pytest.mark.parametrize(
        "scheduled_for, message",
        [
            ("2017-05-01 13:00", "scheduled_for datetime cannot be in the past"),
            ("2017-05-30 13:00", "scheduled_for datetime can only be up to 96 hours in the future"),
            ("not a date", "scheduled_for datetime format is invalid"),
            ("", "scheduled_for must be a non-empty string"),
            (123, "scheduled_for must be a non-empty string"),
            (0, "scheduled_for must be a non-empty string"),
            (False, "scheduled_for must be a non-empty string"),
        ],
    )
    def test_raises_if_scheduled_for_is_invalid(self, notify_db_session, persist_mock, celery_mock, scheduled_for, message):
        service = create_service()
        template = create_template(service=service)

        with pytest.raises(BadRequestError) as e:
            send_one_off_notification(
                service.id,
                {
                    "template_id": str(template.id),
                    "to": "6502532222",
                    "created_by": str(service.created_by_id),
                    "scheduled_for": scheduled_for,
                },
            )

        assert e.value.message.startswith(message)
        assert ScheduledNotification.query.count() == 0
        assert not persist_mock.called

    @freeze_time("2017-05-01 14:00:00")
    def test_sends_simulated_recipients_straight_away(self, notify_db_session, persist_mock, celery_mock, mock_annual_limits):
        service = create_service()
        template = create_template(service=service, template_type=EMAIL_TYPE)

        send_one_off_notification(
            service.id,
            {
                "template_id": str(template.id),
                "to": "simulate-delivered@notification.canada.ca",
                "created_by": str(service.created_by_id),
                "scheduled_for": "2017-05-02 10:00",
            },
        )

        assert persist_mock.called
        assert celery_mock.called
        assert ScheduledNotification.query.count() == 0
