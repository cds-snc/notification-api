from unittest.mock import call

import pytest
from botocore.exceptions import ClientError
from notifications_utils.recipients import InvalidEmailError

import app
from app.celery import provider_tasks
from app.celery.provider_tasks import deliver_email, deliver_sms, deliver_throttled_sms
from app.clients.email.aws_ses import AwsSesClientException
from app.exceptions import NotificationTechnicalFailureException
from celery.exceptions import MaxRetriesExceededError

sms_methods = [
    (deliver_sms, "deliver_sms"),
    (deliver_throttled_sms, "deliver_throttled_sms"),
]


def test_should_have_decorated_tasks_functions():
    assert deliver_sms.__wrapped__.__name__ == "deliver_sms"
    assert deliver_throttled_sms.__wrapped__.__name__ == "deliver_throttled_sms"
    assert deliver_email.__wrapped__.__name__ == "deliver_email"


@pytest.mark.parametrize("sms_method,sms_method_name", sms_methods)
def test_should_call_send_sms_to_provider_from_deliver_sms_task(
    sample_notification,
    mocker,
    sms_method,
    sms_method_name,
):
    mocker.patch("app.delivery.send_to_providers.send_sms_to_provider")

    sms_method(sample_notification.id)
    app.delivery.send_to_providers.send_sms_to_provider.assert_called_with(sample_notification)


@pytest.mark.parametrize("sms_method,sms_method_name", sms_methods)
def test_sms_tasks_should_call_same_method(
    sample_notification,
    mocker,
    sms_method,
    sms_method_name,
):
    private_task = mocker.patch("app.celery.provider_tasks._deliver_sms")

    sms_method(sample_notification.id)
    private_task.assert_called_once()


@pytest.mark.parametrize("sms_method,sms_method_name", sms_methods)
def test_should_add_to_retry_queue_if_notification_not_found_in_deliver_sms_task(
    notify_db_session,
    mocker,
    sms_method,
    sms_method_name,
):
    mocker.patch("app.delivery.send_to_providers.send_sms_to_provider")
    mocker.patch(f"app.celery.provider_tasks.{sms_method_name}.retry")

    notification_id = app.create_uuid()

    sms_method(notification_id)
    app.delivery.send_to_providers.send_sms_to_provider.assert_not_called()

    getattr(app.celery.provider_tasks, sms_method_name).retry.assert_called_with(queue="retry-tasks", countdown=0)


def test_should_call_send_email_to_provider_from_deliver_email_task(
    sample_notification,
    mocker,
):
    mocker.patch("app.delivery.send_to_providers.send_email_to_provider")

    deliver_email(sample_notification.id)
    app.delivery.send_to_providers.send_email_to_provider.assert_called_with(sample_notification)


def test_should_add_to_retry_queue_if_notification_not_found_in_deliver_email_task(
    mocker,
):
    mocker.patch("app.delivery.send_to_providers.send_email_to_provider")
    mocker.patch("app.celery.provider_tasks.deliver_email.retry")

    notification_id = app.create_uuid()

    deliver_email(notification_id)
    app.delivery.send_to_providers.send_email_to_provider.assert_not_called()
    app.celery.provider_tasks.deliver_email.retry.assert_called_with(queue="retry-tasks")


# DO THESE FOR THE 4 TYPES OF TASK


@pytest.mark.parametrize("sms_method,sms_method_name", sms_methods)
def test_should_go_into_technical_error_if_exceeds_retries_on_deliver_sms_task(
    sample_notification,
    mocker,
    sms_method,
    sms_method_name,
):
    mocker.patch(
        "app.delivery.send_to_providers.send_sms_to_provider",
        side_effect=Exception("EXPECTED"),
    )
    mocker.patch(
        f"app.celery.provider_tasks.{sms_method_name}.retry",
        side_effect=MaxRetriesExceededError(),
    )
    queued_callback = mocker.patch("app.celery.provider_tasks._check_and_queue_callback_task")

    with pytest.raises(NotificationTechnicalFailureException) as e:
        sms_method(sample_notification.id)
    assert str(sample_notification.id) in str(e.value)

    getattr(provider_tasks, sms_method_name).retry.assert_called_with(queue="retry-tasks", countdown=300)

    assert sample_notification.status == "technical-failure"
    queued_callback.assert_called_once_with(sample_notification)


def test_should_go_into_technical_error_if_exceeds_retries_on_deliver_email_task(sample_notification, mocker):
    mocker.patch(
        "app.delivery.send_to_providers.send_email_to_provider",
        side_effect=Exception("EXPECTED"),
    )
    mocker.patch(
        "app.celery.provider_tasks.deliver_email.retry",
        side_effect=MaxRetriesExceededError(),
    )
    queued_callback = mocker.patch("app.celery.provider_tasks._check_and_queue_callback_task")

    with pytest.raises(NotificationTechnicalFailureException) as e:
        deliver_email(sample_notification.id)
    assert str(sample_notification.id) in str(e.value)

    provider_tasks.deliver_email.retry.assert_called_with(queue="retry-tasks", countdown=300)
    assert sample_notification.status == "technical-failure"
    queued_callback.assert_called_once_with(sample_notification)


def test_should_technical_error_and_not_retry_if_invalid_email(sample_notification, mocker):
    mocker.patch(
        "app.delivery.send_to_providers.send_email_to_provider",
        side_effect=InvalidEmailError("bad email"),
    )
    mocker.patch("app.celery.provider_tasks.deliver_email.retry")
    logger = mocker.patch("app.celery.provider_tasks.current_app.logger.info")
    queued_callback = mocker.patch("app.celery.provider_tasks._check_and_queue_callback_task")

    deliver_email(sample_notification.id)

    assert provider_tasks.deliver_email.retry.called is False
    assert sample_notification.status == "technical-failure"
    assert (
        call(f"Cannot send notification {sample_notification.id}, got an invalid email address: bad email.")
        in logger.call_args_list
    )
    queued_callback.assert_called_once_with(sample_notification)


def test_should_retry_and_log_exception(sample_notification, mocker):
    error_response = {
        "Error": {
            "Code": "SomeError",
            "Message": "some error message from amazon",
            "Type": "Sender",
        }
    }
    ex = ClientError(error_response=error_response, operation_name="opname")
    mocker.patch(
        "app.delivery.send_to_providers.send_email_to_provider",
        side_effect=AwsSesClientException(str(ex)),
    )
    mocker.patch("app.celery.provider_tasks.deliver_email.retry")

    deliver_email(sample_notification.id)

    assert provider_tasks.deliver_email.retry.called is True
    assert sample_notification.status == "created"


@pytest.mark.parametrize("sms_method,sms_method_name", sms_methods)
def test_send_sms_should_not_switch_providers_on_non_provider_failure(
    sample_notification,
    mocker,
    sms_method,
    sms_method_name,
):
    mocker.patch(
        "app.delivery.send_to_providers.send_sms_to_provider",
        side_effect=Exception("Non Provider Exception"),
    )
    switch_provider_mock = mocker.patch("app.delivery.send_to_providers.dao_toggle_sms_provider")
    mocker.patch(f"app.celery.provider_tasks.{sms_method_name}.retry")

    sms_method(sample_notification.id)

    assert switch_provider_mock.called is False
