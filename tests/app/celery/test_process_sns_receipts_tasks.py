import pytest

from datetime import datetime

from freezegun import freeze_time

from app import statsd_client
from app.celery.process_sns_receipts_tasks import process_sns_results
from app.notifications.callbacks import create_delivery_status_callback_data
from app.dao.notifications_dao import get_notification_by_id
from app.models import (
    NOTIFICATION_SENT,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_TECHNICAL_FAILURE,
)
from tests.app.db import (
    create_service_callback_api,
    sns_success_callback,
    sns_failed_callback,
    create_notification,
)
from tests.app.conftest import sample_notification as create_sample_notification


def test_process_sns_results_delivered(sample_template, notify_db, notify_db_session, mocker):
    mock_logger = mocker.patch('app.celery.process_sns_receipts_tasks.current_app.logger.info')

    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_template,
        reference='ref',
        status=NOTIFICATION_SENT,
        sent_by='sns',
        sent_at=datetime.utcnow()
    )
    assert get_notification_by_id(notification.id).status == NOTIFICATION_SENT
    assert process_sns_results(sns_success_callback(reference='ref'))
    assert get_notification_by_id(notification.id).status == NOTIFICATION_DELIVERED
    assert get_notification_by_id(notification.id).provider_response is None

    mock_logger.assert_called_once_with(f'SNS callback return status of delivered for notification: {notification.id}')


@pytest.mark.parametrize("provider_response, expected_status, should_log_warning, should_save_provider_response", [
    ("Blocked as spam by phone carrier", NOTIFICATION_TECHNICAL_FAILURE, False, True),
    ('Phone carrier is currently unreachable/unavailable', NOTIFICATION_TEMPORARY_FAILURE, False, False),
    ('Phone is currently unreachable/unavailable', NOTIFICATION_PERMANENT_FAILURE, False, False),
    ("This is not a real response", NOTIFICATION_TECHNICAL_FAILURE, True, False),
])
def test_process_sns_results_failed(
    sample_template,
    notify_db,
    notify_db_session,
    mocker,
    provider_response,
    expected_status,
    should_log_warning,
    should_save_provider_response,
):
    mock_logger = mocker.patch('app.celery.process_sns_receipts_tasks.current_app.logger.info')
    mock_warning_logger = mocker.patch('app.celery.process_sns_receipts_tasks.current_app.logger.warning')

    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_template,
        reference='ref',
        status=NOTIFICATION_SENT,
        sent_by='sns',
        sent_at=datetime.utcnow()
    )
    assert get_notification_by_id(notification.id).status == NOTIFICATION_SENT
    assert process_sns_results(sns_failed_callback(provider_response=provider_response, reference='ref'))
    assert get_notification_by_id(notification.id).status == expected_status

    if should_save_provider_response:
        assert get_notification_by_id(notification.id).provider_response == provider_response
    else:
        assert get_notification_by_id(notification.id).provider_response is None

    mock_logger.assert_called_once_with((
        f'SNS delivery failed: notification id {notification.id} and reference ref has error found. '
        f'Provider response: {provider_response}'
    ))

    assert mock_warning_logger.call_count == int(should_log_warning)


def test_sns_callback_should_retry_if_notification_is_new(mocker):
    mock_retry = mocker.patch('app.celery.process_sns_receipts_tasks.process_sns_results.retry')
    mock_logger = mocker.patch('app.celery.process_sns_receipts_tasks.current_app.logger.error')

    with freeze_time('2017-11-17T12:14:03.646Z'):
        assert process_sns_results(sns_success_callback(reference='ref', timestamp='2017-11-17T12:14:02.000Z')) is None
        assert mock_logger.call_count == 0
        assert mock_retry.call_count == 1


def test_sns_callback_should_log_if_notification_is_missing(mocker):
    mock_retry = mocker.patch('app.celery.process_sns_receipts_tasks.process_sns_results.retry')
    mock_logger = mocker.patch('app.celery.process_sns_receipts_tasks.current_app.logger.warning')

    with freeze_time('2017-11-17T12:34:03.646Z'):
        assert process_sns_results(sns_success_callback(reference='ref')) is None
        assert mock_retry.call_count == 0
        mock_logger.assert_called_once_with('notification not found for reference: ref (update to delivered)')


def test_sns_callback_should_not_retry_if_notification_is_old(client, notify_db, mocker):
    mock_retry = mocker.patch('app.celery.process_sns_receipts_tasks.process_sns_results.retry')
    mock_logger = mocker.patch('app.celery.process_sns_receipts_tasks.current_app.logger.error')

    with freeze_time('2017-11-17T12:16:00.000Z'):  # 6 minutes apart and max is 5 minutes
        assert process_sns_results(sns_success_callback(reference='ref', timestamp='2017-11-17T12:10:00.000Z')) is None
        assert mock_logger.call_count == 0
        assert mock_retry.call_count == 0


def test_process_sns_results_retry_called(sample_template, mocker):
    create_notification(
        sample_template,
        reference='ref1',
        sent_at=datetime.utcnow(),
        status=NOTIFICATION_SENT,
        sent_by='sns'
    )

    mocker.patch("app.dao.notifications_dao._update_notification_status", side_effect=Exception("EXPECTED"))
    mocked = mocker.patch('app.celery.process_sns_receipts_tasks.process_sns_results.retry')
    process_sns_results(response=sns_success_callback(reference='ref1'))
    assert mocked.call_count == 1


def test_process_sns_results_does_not_process_other_providers(sample_template, mocker):
    mock_logger = mocker.patch('app.celery.process_sns_receipts_tasks.current_app.logger.exception')
    mock_dao = mocker.patch("app.dao.notifications_dao._update_notification_status")
    create_notification(
        sample_template,
        reference='ref1',
        sent_at=datetime.utcnow(),
        status=NOTIFICATION_SENT,
        sent_by='pinpoint'
    )

    process_sns_results(response=sns_success_callback(reference='ref1')) is None
    assert mock_logger.called_once_with('')
    assert not mock_dao.called


def test_process_sns_results_calls_service_callback(
    sample_template,
    notify_db_session,
    notify_db,
    mocker
):
    with freeze_time('2021-01-01T12:00:00'):
        mocker.patch('app.statsd_client.incr')
        mocker.patch('app.statsd_client.timing_with_dates')
        send_mock = mocker.patch(
            'app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async'
        )
        notification = create_sample_notification(
            notify_db,
            notify_db_session,
            template=sample_template,
            reference='ref',
            status=NOTIFICATION_SENT,
            sent_by='sns',
            sent_at=datetime.utcnow()
        )
        callback_api = create_service_callback_api(
            service=sample_template.service,
            url="https://example.com"
        )
        assert get_notification_by_id(notification.id).status == NOTIFICATION_SENT

        assert process_sns_results(sns_success_callback(reference='ref'))
        assert get_notification_by_id(notification.id).status == NOTIFICATION_DELIVERED
        assert get_notification_by_id(notification.id).provider_response is None
        statsd_client.timing_with_dates.assert_any_call(
            "callback.sns.elapsed-time", datetime.utcnow(), notification.sent_at
        )
        statsd_client.incr.assert_any_call("callback.sns.delivered")
        updated_notification = get_notification_by_id(notification.id)
        encrypted_data = create_delivery_status_callback_data(updated_notification, callback_api)
        send_mock.assert_called_once_with(
            [str(notification.id), encrypted_data],
            queue="service-callbacks"
        )
