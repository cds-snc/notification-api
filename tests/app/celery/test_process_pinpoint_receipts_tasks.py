from datetime import datetime

import pytest
from freezegun import freeze_time

from app import statsd_client
from app.aws.mocks import pinpoint_failed_callback, pinpoint_success_callback
from app.celery.process_pinpoint_receipts_tasks import process_pinpoint_results
from app.dao.notifications_dao import get_notification_by_id
from app.models import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
)
from app.notifications.callbacks import create_delivery_status_callback_data
from celery.exceptions import MaxRetriesExceededError
from tests.app.conftest import create_sample_notification
from tests.app.db import (
    create_notification,
    create_service_callback_api,
    save_notification,
)


def test_process_pinpoint_results_delivered(sample_template, notify_db, notify_db_session, mocker):
    mock_logger = mocker.patch("app.celery.process_pinpoint_receipts_tasks.current_app.logger.info")

    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_template,
        reference="ref",
        status=NOTIFICATION_SENT,
        sent_by="pinpoint",
        sent_at=datetime.utcnow(),
    )
    assert get_notification_by_id(notification.id).status == NOTIFICATION_SENT
    assert process_pinpoint_results(pinpoint_success_callback(reference="ref"))
    assert get_notification_by_id(notification.id).status == NOTIFICATION_DELIVERED
    assert get_notification_by_id(notification.id).provider_response == "Message has been accepted by phone"

    mock_logger.assert_called_once_with(f"Pinpoint callback return status of delivered for notification: {notification.id}")


@pytest.mark.parametrize(
    "provider_response, expected_status, should_log_warning, should_save_provider_response",
    [
        (
            "Blocked as spam by phone carrier",
            NOTIFICATION_TECHNICAL_FAILURE,
            False,
            True,
        ),
        (
            "Phone carrier is currently unreachable/unavailable",
            NOTIFICATION_TEMPORARY_FAILURE,
            False,
            True,
        ),
        (
            "Phone is currently unreachable/unavailable",
            NOTIFICATION_PERMANENT_FAILURE,
            False,
            True,
        ),
        ("This is not a real response", NOTIFICATION_TECHNICAL_FAILURE, True, True),
    ],
)
def test_process_pinpoint_results_failed(
    sample_template,
    notify_db,
    notify_db_session,
    mocker,
    provider_response,
    expected_status,
    should_log_warning,
    should_save_provider_response,
):
    mock_logger = mocker.patch("app.celery.process_pinpoint_receipts_tasks.current_app.logger.info")
    mock_warning_logger = mocker.patch("app.celery.process_pinpoint_receipts_tasks.current_app.logger.warning")

    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_template,
        reference="ref",
        status=NOTIFICATION_SENT,
        sent_by="pinpoint",
        sent_at=datetime.utcnow(),
    )
    assert get_notification_by_id(notification.id).status == NOTIFICATION_SENT
    assert process_pinpoint_results(pinpoint_failed_callback(provider_response=provider_response, reference="ref"))
    assert get_notification_by_id(notification.id).status == expected_status

    if should_save_provider_response:
        assert get_notification_by_id(notification.id).provider_response == provider_response
    else:
        assert get_notification_by_id(notification.id).provider_response is None

    mock_logger.assert_called_once_with(
        (
            f"Pinpoint delivery failed: notification id {notification.id} and reference ref has error found. "
            f"Provider response: {provider_response}"
        )
    )

    assert mock_warning_logger.call_count == int(should_log_warning)


def test_pinpoint_callback_should_retry_if_notification_is_missing(notify_db, mocker):
    mock_retry = mocker.patch("app.celery.process_pinpoint_receipts_tasks.process_pinpoint_results.retry")
    assert process_pinpoint_results(pinpoint_success_callback(reference="ref")) is None
    assert mock_retry.call_count == 1


def test_pinpoint_callback_should_give_up_after_max_tries(notify_db, mocker):
    mocker.patch(
        "app.celery.process_pinpoint_receipts_tasks.process_pinpoint_results.retry",
        side_effect=MaxRetriesExceededError,
    )
    mock_logger = mocker.patch("app.celery.process_pinpoint_receipts_tasks.current_app.logger.warning")

    assert process_pinpoint_results(pinpoint_success_callback(reference="ref")) is None
    mock_logger.assert_called_with("notification not found for Pinpoint reference: ref (update to delivered). Giving up.")


def test_process_pinpoint_results_retry_called(sample_template, mocker):
    save_notification(
        create_notification(
            sample_template,
            reference="ref1",
            sent_at=datetime.utcnow(),
            status=NOTIFICATION_SENT,
            sent_by="pinpoint",
        )
    )

    mocker.patch(
        "app.dao.notifications_dao._update_notification_status",
        side_effect=Exception("EXPECTED"),
    )
    mocked = mocker.patch("app.celery.process_pinpoint_receipts_tasks.process_pinpoint_results.retry")
    process_pinpoint_results(response=pinpoint_success_callback(reference="ref1"))
    assert mocked.call_count == 1


def test_process_pinpoint_results_does_not_process_other_providers(sample_template, mocker):
    mock_logger = mocker.patch("app.celery.process_pinpoint_receipts_tasks.current_app.logger.exception")
    mock_dao = mocker.patch("app.dao.notifications_dao._update_notification_status")
    save_notification(
        create_notification(
            sample_template,
            reference="ref1",
            sent_at=datetime.utcnow(),
            status=NOTIFICATION_SENT,
            sent_by="sns",
        )
    )

    process_pinpoint_results(response=pinpoint_success_callback(reference="ref1")) is None
    assert mock_logger.called_once_with("")
    assert not mock_dao.called


def test_process_pinpoint_results_calls_service_callback(sample_template, notify_db_session, notify_db, mocker):
    with freeze_time("2021-01-01T12:00:00"):
        mocker.patch("app.statsd_client.incr")
        mocker.patch("app.statsd_client.timing_with_dates")
        send_mock = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async")
        notification = create_sample_notification(
            notify_db,
            notify_db_session,
            template=sample_template,
            reference="ref",
            status=NOTIFICATION_SENT,
            sent_by="pinpoint",
            sent_at=datetime.utcnow(),
        )
        callback_api = create_service_callback_api(service=sample_template.service, url="https://example.com")
        assert get_notification_by_id(notification.id).status == NOTIFICATION_SENT

        assert process_pinpoint_results(pinpoint_success_callback(reference="ref"))
        assert get_notification_by_id(notification.id).status == NOTIFICATION_DELIVERED
        assert get_notification_by_id(notification.id).provider_response == "Message has been accepted by phone"
        statsd_client.timing_with_dates.assert_any_call("callback.pinpoint.elapsed-time", datetime.utcnow(), notification.sent_at)
        statsd_client.incr.assert_any_call("callback.pinpoint.delivered")
        updated_notification = get_notification_by_id(notification.id)
        signed_data = create_delivery_status_callback_data(updated_notification, callback_api)
        send_mock.assert_called_once_with([str(notification.id), signed_data], queue="service-callbacks")
