from datetime import datetime

import pytest
from freezegun import freeze_time

from app import statsd_client
from app.aws.mocks import (
    pinpoint_delivered_callback,
    pinpoint_delivered_callback_missing_sms_data,
    pinpoint_failed_callback,
    pinpoint_shortcode_delivered_callback,
    pinpoint_successful_callback,
)
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


@pytest.mark.parametrize(
    "callback, expected_response, origination_phone_number",
    [
        (pinpoint_delivered_callback, "Message has been accepted by phone", "+13655550100"),
        (pinpoint_shortcode_delivered_callback, "Message has been accepted by phone carrier", "555555"),
    ],
)
def test_process_pinpoint_results_delivered(
    sample_template, notify_db, notify_db_session, callback, expected_response, origination_phone_number, mocker
):
    mock_logger = mocker.patch("app.celery.process_pinpoint_receipts_tasks.current_app.logger.info")
    mock_callback_task = mocker.patch("app.notifications.callbacks._check_and_queue_callback_task")

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

    process_pinpoint_results(callback(reference="ref"))

    assert mock_callback_task.called_once_with(get_notification_by_id(notification.id))
    assert get_notification_by_id(notification.id).status == NOTIFICATION_DELIVERED
    assert get_notification_by_id(notification.id).provider_response == expected_response
    assert float(get_notification_by_id(notification.id).sms_total_message_price) == 0.00581
    assert float(get_notification_by_id(notification.id).sms_total_carrier_fee) == 0.006
    assert get_notification_by_id(notification.id).sms_iso_country_code == "CA"
    assert get_notification_by_id(notification.id).sms_carrier_name == "Bell"
    assert get_notification_by_id(notification.id).sms_message_encoding == "GSM"
    assert get_notification_by_id(notification.id).sms_origination_phone_number == origination_phone_number

    mock_logger.assert_called_once_with(f"Pinpoint callback return status of delivered for notification: {notification.id}")


def test_process_pinpoint_results_succeeded(sample_template, notify_db, notify_db_session, mocker):
    mock_callback_task = mocker.patch("app.notifications.callbacks._check_and_queue_callback_task")

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

    process_pinpoint_results(pinpoint_successful_callback(reference="ref"))

    assert mock_callback_task.not_called()
    assert get_notification_by_id(notification.id).status == NOTIFICATION_SENT
    assert get_notification_by_id(notification.id).provider_response is None


def test_process_pinpoint_results_missing_sms_data(sample_template, notify_db, notify_db_session, mocker):
    mock_callback_task = mocker.patch("app.notifications.callbacks._check_and_queue_callback_task")

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

    process_pinpoint_results(pinpoint_delivered_callback_missing_sms_data(reference="ref"))

    assert mock_callback_task.called_once_with(get_notification_by_id(notification.id))
    assert get_notification_by_id(notification.id).status == NOTIFICATION_DELIVERED
    assert float(get_notification_by_id(notification.id).sms_total_message_price) == 0.00581
    assert float(get_notification_by_id(notification.id).sms_total_carrier_fee) == 0.006
    assert get_notification_by_id(notification.id).sms_iso_country_code is None
    assert get_notification_by_id(notification.id).sms_carrier_name is None


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
    mock_callback_task = mocker.patch("app.notifications.callbacks._check_and_queue_callback_task")

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
    process_pinpoint_results(pinpoint_failed_callback(provider_response=provider_response, reference="ref"))

    assert mock_callback_task.called_once_with(get_notification_by_id(notification.id))
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
    mock_callback_task = mocker.patch("app.notifications.callbacks._check_and_queue_callback_task")

    process_pinpoint_results(pinpoint_delivered_callback(reference="ref"))

    mock_callback_task.assert_not_called()
    assert mock_retry.call_count == 1


def test_pinpoint_callback_should_give_up_after_max_tries(notify_db, mocker):
    mocker.patch(
        "app.celery.process_pinpoint_receipts_tasks.process_pinpoint_results.retry",
        side_effect=MaxRetriesExceededError,
    )
    mock_logger = mocker.patch("app.celery.process_pinpoint_receipts_tasks.current_app.logger.warning")
    mock_callback_task = mocker.patch("app.notifications.callbacks._check_and_queue_callback_task")

    process_pinpoint_results(pinpoint_delivered_callback(reference="ref")) is None
    mock_callback_task.assert_not_called()

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
    process_pinpoint_results(response=pinpoint_delivered_callback(reference="ref1"))
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

    process_pinpoint_results(response=pinpoint_delivered_callback(reference="ref1")) is None
    assert mock_logger.called_once_with("")
    assert not mock_dao.called


def test_process_pinpoint_results_calls_service_callback(sample_template, notify_db_session, notify_db, mocker):
    with freeze_time("2021-01-01T12:00:00"):
        mocker.patch("app.statsd_client.incr")
        mocker.patch("app.statsd_client.timing_with_dates")
        mock_send_status = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async")
        mock_callback = mocker.patch("app.notifications.callbacks._check_and_queue_callback_task")

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

        process_pinpoint_results(pinpoint_delivered_callback(reference="ref"))

        assert mock_callback.called_once_with(get_notification_by_id(notification.id))
        assert get_notification_by_id(notification.id).status == NOTIFICATION_DELIVERED
        assert get_notification_by_id(notification.id).provider_response == "Message has been accepted by phone"
        statsd_client.timing_with_dates.assert_any_call("callback.pinpoint.elapsed-time", datetime.utcnow(), notification.sent_at)
        statsd_client.incr.assert_any_call("callback.pinpoint.delivered")
        updated_notification = get_notification_by_id(notification.id)
        signed_data = create_delivery_status_callback_data(updated_notification, callback_api)
        mock_send_status.assert_called_once_with(
            [str(notification.id), signed_data, notification.service_id], queue="service-callbacks"
        )
