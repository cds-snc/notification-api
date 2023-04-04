import pytest
from app.celery import process_delivery_status_result_tasks
from celery.exceptions import Retry


@pytest.fixture
def sample_translate_return_value():
    return {
        "payload": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDI",
        "reference": "MessageSID",
        "record_status": "sent",
    }


@pytest.fixture
def sample_delivery_status_result_message():
    return {
        "message": {
            "body": "UmF3RGxyRG9uZURhdGU9MjMwMzIyMjMzOCZTbXNTaWQ9U014eHgmU21zU3RhdHV"
            "zPWRlbGl2ZXJlZCZNZXNzYWdlU3RhdHVzPWRlbGl2ZXJlZCZUbz0lMkIxMTExMTExMTExMSZ"
            "NZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMzMzNDQ0NCZB"
            "cGlWZXJzaW9uPTIwMTAtMDQtMDE=",
            "provider": "twilio",
        }
    }


def test_event_message_invalid_message(
    mocker,
    notify_db_session,
    sample_delivery_status_result_message,
    sample_translate_return_value,
    sample_notification,
):
    """Test that celery will retry the task if "message" is missing from the CeleryEvent message"""

    # remove message (key) from the sample_delivery_status_result_message
    sample_delivery_status_result_message.pop("message")

    # mock translate_delivery_status() when called within process_delivery_status_result_tasks()
    mocker.patch("app.clients")
    mocker.patch("app.clients.sms.SmsClient")
    mocker.patch(
        "app.clients.sms.twilio.TwilioSMSClient.translate_delivery_status",
        return_value=sample_translate_return_value,
    )

    with pytest.raises(Retry):
        process_delivery_status_result_tasks.process_delivery_status(
            event=sample_delivery_status_result_message
        )


def test_without_provider(
    mocker,
    notify_db_session,
    sample_delivery_status_result_message,
    sample_translate_return_value,
    sample_notification,
):
    """Test that celery will retry the task if provider doesnt exist then self.retry is called"""

    # change message['provider'] to invalid provider name
    sample_delivery_status_result_message["message"]["provider"] = "abc"
    mocker.patch("app.clients")
    mocker.patch("app.clients.sms.SmsClient")
    mocker.patch(
        "app.clients.sms.twilio.TwilioSMSClient.translate_delivery_status",
        return_value=sample_translate_return_value,
    )
    mocker.patch(
        "app.celery.process_delivery_status_result_tasks.attempt_to_get_notification",
        return_value=(sample_notification, False, False),
    )

    with pytest.raises(Retry):
        process_delivery_status_result_tasks.process_delivery_status(
            event=sample_delivery_status_result_message
        )


def test_attempt_get_notification_triggers_should_retry(
    mocker,
    notify_db_session,
    sample_delivery_status_result_message,
    sample_translate_return_value,
    sample_notification,
):
    """
    Test that celery task will retry the task if callback event for reference was received less than five minutes ago
    """
    mocker.patch("app.clients")
    mocker.patch("app.clients.sms.SmsClient")
    mocker.patch(
        "app.clients.sms.twilio.TwilioSMSClient.translate_delivery_status",
        return_value=sample_translate_return_value,
    )
    mocker.patch(
        "app.celery.process_delivery_status_result_tasks.attempt_to_get_notification",
        return_value=(sample_notification, True, False),
    )

    with pytest.raises(Retry):
        process_delivery_status_result_tasks.process_delivery_status(
            event=sample_delivery_status_result_message
        )


def test_attempt_to_get_notification_none(
    mocker,
    notify_db_session,
    sample_delivery_status_result_message,
    sample_translate_return_value,
    sample_notification,
):
    """We want to test that attempt_to_get_notification triggers a celery Retry when None"""
    mocker.patch("app.clients")
    mocker.patch("app.clients.sms.SmsClient")
    mocker.patch(
        "app.clients.sms.twilio.TwilioSMSClient.translate_delivery_status",
        return_value=sample_translate_return_value,
    )
    mocker.patch(
        "app.celery.process_delivery_status_result_tasks.attempt_to_get_notification",
        return_value=(None, False, False),
    )

    with pytest.raises(Retry):
        process_delivery_status_result_tasks.process_delivery_status(
            event=sample_delivery_status_result_message
        )


def test_missing_body_triggers_retry(
    notify_db_session,
    sample_delivery_status_result_message,
    sample_translate_return_value,
    sample_notification,
):
    """Verify that retry is triggered if translate_delivery_status is given a body does not exist"""
    # change message['body'] to invalid body
    sample_delivery_status_result_message["message"].pop("body")
    with pytest.raises(Retry):
        process_delivery_status_result_tasks.process_delivery_status(
            event=sample_delivery_status_result_message
        )


def test_none_notification_platform_status_triggers_retry(
    mocker,
    notify_db_session,
    sample_delivery_status_result_message,
    sample_translate_return_value,
    sample_notification,
):
    """verify that retry is triggered if translate_delivery_status is returns a None"""

    mocker.patch("app.clients")
    mocker.patch("app.clients.sms.SmsClient")
    mocker.patch(
        "app.clients.sms.twilio.TwilioSMSClient.translate_delivery_status",
        return_value=None,
    )

    with pytest.raises(Retry):
        process_delivery_status_result_tasks.process_delivery_status(
            event=sample_delivery_status_result_message
        )


def test_invalid_body_triggers_retry(
    notify_db_session,
    sample_delivery_status_result_message,
    sample_translate_return_value,
    sample_notification,
):
    """
    verify that retry is triggered if translate_delivery_status is given a body is missing properties
    """

    # change message['body'] to invalid body
    sample_delivery_status_result_message["message"]["body"] = ""
    with pytest.raises(Retry):
        process_delivery_status_result_tasks.process_delivery_status(
            event=sample_delivery_status_result_message
        )


def test_should_exit(
    mocker, notify_db_session, sample_delivery_status_result_message, sample_notification
):
    """Test that celery task will "exit" if multiple notifications were found"""
    mocker.patch(
        "app.celery.process_delivery_status_result_tasks.attempt_to_get_notification",
        return_value=(sample_notification, False, True),
    )

    assert not process_delivery_status_result_tasks.process_delivery_status(
        event=sample_delivery_status_result_message
    )


# we want to test that celery task will succeed when correct data is given
def test_with_correct_data(
    mocker,
    notify_db_session,
    sample_delivery_status_result_message,
    sample_translate_return_value,
    sample_notification,
):
    """Test that celery task will complete if correct data is provided"""

    mocker.patch("app.clients")
    mocker.patch("app.clients.sms.SmsClient")
    mocker.patch(
        "app.clients.sms.twilio.TwilioSMSClient.translate_delivery_status",
        return_value=sample_translate_return_value,
    )
    mocker.patch(
        "app.celery.process_delivery_status_result_tasks.attempt_to_get_notification",
        return_value=(sample_notification, False, False),
    )

    assert process_delivery_status_result_tasks.process_delivery_status(
        event=sample_delivery_status_result_message
    )
