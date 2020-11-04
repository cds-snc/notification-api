from datetime import datetime

from freezegun import freeze_time

from app.celery.process_sns_receipts_tasks import process_sns_results
from app.dao.notifications_dao import get_notification_by_id
from tests.app.db import (
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
        status='sent',
        sent_by='sns',
        sent_at=datetime.utcnow()
    )
    assert get_notification_by_id(notification.id).status == 'sent'
    assert process_sns_results(sns_success_callback(reference='ref'))
    assert get_notification_by_id(notification.id).status == 'delivered'

    mock_logger.assert_called_once_with(f'SNS callback return status of delivered for notification: {notification.id}')


def test_process_sns_results_failed(sample_template, notify_db, notify_db_session, mocker):
    mock_logger = mocker.patch('app.celery.process_sns_receipts_tasks.current_app.logger.info')

    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_template,
        reference='ref',
        status='sent',
        sent_by='sns',
        sent_at=datetime.utcnow()
    )
    assert get_notification_by_id(notification.id).status == 'sent'
    assert process_sns_results(sns_failed_callback(reference='ref'))
    assert get_notification_by_id(notification.id).status == 'failed'

    mock_logger.assert_called_once_with((
        f'SNS delivery failed: notification id {notification.id} and reference ref has error found. '
        'Provider response: Unknown error attempting to reach phone'
    ))


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
        status='sent',
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
        status='sent',
        sent_by='pinpoint'
    )

    process_sns_results(response=sns_success_callback(reference='ref1')) is None
    assert mock_logger.called_once_with('')
    assert not mock_dao.called
