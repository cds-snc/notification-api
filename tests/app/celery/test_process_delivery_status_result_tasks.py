from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm.exc import MultipleResultsFound

from app.clients.sms import UNABLE_TO_TRANSLATE, SmsStatusRecord
from app.clients.sms.twilio import TwilioSMSClient
from app.celery.exceptions import AutoRetryException, NonRetryableException
from app.celery.process_delivery_status_result_tasks import (
    _get_include_payload_status,
    _get_notification,
    _get_provider_info,
    get_notification_platform_status,
    process_delivery_status,
    sms_status_update,
)
from app.dao.notifications_dao import (
    dao_get_notification_by_reference,
    _CREATED_UPDATES,
    _SENDING_UPDATES,
    _PENDING_UPDATES,
    _SENT_UPDATES,
    _DELIVERED_UPDATES,
    _TEMPORARY_FAILURE_UPDATES,
    _PERMANENT_FAILURE_UPDATES,
    _TECHNICAL_FAILURE_UPDATES,
    _PREFERENCES_DECLINED_UPDATES,
)
from app.constants import (
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_PERMANENT_FAILURE,
    PINPOINT_PROVIDER,
    NOTIFICATION_PREFERENCES_DECLINED,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    TWILIO_PROVIDER,
)


@pytest.fixture
def sample_delivery_status_result_message():
    return {
        'message': {
            'body': 'UmF3RGxyRG9uZURhdGU9MjMwMzIyMjMzOCZTbXNTaWQ9U014eHgmU21zU3RhdHV'
            'zPWRlbGl2ZXJlZCZNZXNzYWdlU3RhdHVzPWRlbGl2ZXJlZCZUbz0lMkIxMTExMTExMTExMSZ'
            'NZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMzMzNDQ0NCZB'
            'cGlWZXJzaW9uPTIwMTAtMDQtMDE=',
            'provider': TWILIO_PROVIDER,
        }
    }


@pytest.fixture()
def sample_notification_platform_status():
    return {
        'payload': 'UmF3RGxyRG9uZURhdGU9MjMwMzIyMjMzOCZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYWdlU3RhdHVzPWR'
        'lbGl2ZXJlZCZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNaGFyZGNvZGVkS1dNJkFjY291bnRTaWQ9QUN6enomRnJvbT'
        '0lMkIxMjIyMzMzNDQ0NCZBcGlWZXJzaW9uPTIwMTAtMDQtMDE=',
        'reference': 'SMhardcodedKWM',
        'record_status': NOTIFICATION_DELIVERED,
    }


@pytest.fixture()
def sample_sqs_message_with_provider():
    return {
        'body': 'UmF3RGxyRG9uZURhdGU9MjMwMzIyMjMzOCZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYWdlU3RhdHV'
        'zPWRlbGl2ZXJlZCZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIx'
        'MjIyMzMzNDQ0NCZBcGlWZXJzaW9uPTIwMTAtMDQtMDE=',
        'provider': 'sms',
    }


@pytest.fixture()
def sample_sqs_message_without_provider():
    return {
        'body': 'UmF3RGxyRG9uZURhdGU9MjMwMzIyMjMzOCZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYWdlU3RhdHV'
        'zPWRlbGl2ZXJlZCZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIx'
        'MjIyMzMzNDQ0NCZBcGlWZXJzaW9uPTIwMTAtMDQtMDE='
    }


def test_celery_retry_event_when_missing_message_attribute(sample_delivery_status_result_message):
    """Test that celery will retry the task if "message" is missing from the CeleryEvent message"""

    del sample_delivery_status_result_message['message']
    with pytest.raises(NonRetryableException) as exc_info:
        process_delivery_status(event=sample_delivery_status_result_message)
    assert UNABLE_TO_TRANSLATE in str(exc_info)


def test_celery_event_with_missing_provider_attribute(sample_delivery_status_result_message):
    """Test that celery will retry the task if "provider" is missing from the CeleryEvent message"""

    del sample_delivery_status_result_message['message']['provider']
    with pytest.raises(NonRetryableException) as exc_info:
        process_delivery_status(event=sample_delivery_status_result_message)
    assert UNABLE_TO_TRANSLATE in str(exc_info)


def test_celery_event_with_missing_body_attribute(sample_delivery_status_result_message):
    """Test that celery will retry the task if "body" is missing from the CeleryEvent message"""

    del sample_delivery_status_result_message['message']['body']
    with pytest.raises(NonRetryableException) as exc_info:
        process_delivery_status(event=sample_delivery_status_result_message)
    assert UNABLE_TO_TRANSLATE in str(exc_info)


def test_celery_event_with_invalid_provider_attribute(sample_delivery_status_result_message):
    """Test that celery will retry the task if "message" is invalid from the CeleryEvent message"""

    sample_delivery_status_result_message['message']['provider'] = 'abc123'
    with pytest.raises(NonRetryableException) as exc_info:
        process_delivery_status(event=sample_delivery_status_result_message)
    assert UNABLE_TO_TRANSLATE in str(exc_info)


def test_celery_event_with_invalid_body_attribute(sample_delivery_status_result_message):
    """Test that celery will retry the task if "message" is missing from the CeleryEvent message"""

    sample_delivery_status_result_message['message']['body'] = 'body'
    with pytest.raises(NonRetryableException) as exc_info:
        process_delivery_status(event=sample_delivery_status_result_message)
    assert UNABLE_TO_TRANSLATE in str(exc_info)


def test_get_provider_info_with_no_provider_retries(notify_api, sample_sqs_message_without_provider):
    """Test get_provider_info() retries when no provider is given by the celery event"""

    with pytest.raises(NonRetryableException) as exc_info:
        _get_provider_info(sample_sqs_message_without_provider)
    assert UNABLE_TO_TRANSLATE in str(exc_info)


def test_get_provider_info_with_invalid_provider_retries(notify_api, sample_sqs_message_with_provider):
    """Test that _get_provider_info() will raise a celery retry when sqs message has an invalid provider"""

    sample_sqs_message_with_provider['provider'] = 'abc'

    # now supply the sample to the function we want to test with the expectation of failure
    with pytest.raises(NonRetryableException) as exc_info:
        _get_provider_info(sample_sqs_message_with_provider)
    assert UNABLE_TO_TRANSLATE in str(exc_info)


def test_get_provider_info_with_twilio(notify_api, sample_sqs_message_with_provider):
    sample_sqs_message_with_provider['provider'] = TWILIO_PROVIDER

    # now supply the sample to the function we want to test
    provider_name_output, provider = _get_provider_info(sample_sqs_message_with_provider)

    assert provider.name == TWILIO_PROVIDER
    assert provider_name_output == TWILIO_PROVIDER


@pytest.mark.serial
def test_process_delivery_status_with_invalid_notification_retries(sample_delivery_status_result_message):
    """Notification is invalid because there are no notifications in the database"""
    with pytest.raises(Exception) as exc_info:
        # Fixture is base64 encoded and uses reference: SMyyy, refernces cannot be hard-coded for non-serial tests
        process_delivery_status(event=sample_delivery_status_result_message)
    assert exc_info.type is AutoRetryException


def test_none_notification_platform_status_triggers_retry(mocker, sample_delivery_status_result_message):
    """Verify that retry is triggered if translate_delivery_status returns None"""

    mocker.patch('app.clients')
    mocker.patch('app.clients.sms.twilio.TwilioSMSClient.translate_delivery_status', return_value=None)

    with pytest.raises(Exception) as exc_info:
        # Fixture is base64 encoded and uses reference: SMyyy, refernces cannot be hard-coded for non-serial tests
        process_delivery_status(event=sample_delivery_status_result_message)
    assert exc_info.type is AutoRetryException


def test_process_delivery_status_should_retry_preempts_exit(sample_delivery_status_result_message):
    with pytest.raises(Exception) as exc_info:
        process_delivery_status(event=sample_delivery_status_result_message)
    assert exc_info.type is AutoRetryException


@pytest.mark.serial
def test_process_delivery_status_with_valid_message_with_no_payload(
    mocker,
    sample_delivery_status_result_message,
    sample_template,
    sample_notification,
):
    """
    Test that the Celery task will complete if correct data is provided.
    """

    # This test is marked "serial" because the reference is used by many tests.  Making it a random
    # value causes the test to fail.
    sample_notification(
        template=sample_template(), reference='SMyyy', sent_at=datetime.now(timezone.utc), status=NOTIFICATION_SENT
    )

    callback_mock = mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')
    process_delivery_status(event=sample_delivery_status_result_message)

    callback_mock.assert_called_once()
    assert callback_mock.call_args.args[1] is None


@pytest.mark.serial
def test_process_delivery_status_with_valid_message_with_payload(
    mocker,
    sample_delivery_status_result_message,
    sample_template,
    sample_notification,
):
    """
    Test that the Celery task will complete if correct data is provided.
    """

    # This test is marked "serial" because the reference is used by many tests.  Making it a random
    # value causes the test to fail.
    sample_notification(
        template=sample_template(), reference='SMyyy', sent_at=datetime.now(timezone.utc), status=NOTIFICATION_SENT
    )

    mocker.patch('app.celery.process_delivery_status_result_tasks._get_include_payload_status', returns=True)
    callback_mock = mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')
    process_delivery_status(event=sample_delivery_status_result_message)
    callback_mock.assert_called_once()


@pytest.mark.serial
def test_wt_delivery_status_callback_should_log_total_time(
    mocker,
    client,
    sample_template,
    sample_notification,
    sample_delivery_status_result_message,
):
    mock_log_total_time = mocker.patch('app.celery.common.log_notification_total_time')
    mocker.patch('app.celery.service_callback_tasks.check_and_queue_callback_task')

    notification = sample_notification(template=sample_template(), status=NOTIFICATION_SENT, reference='SMyyy')
    # Mock db call
    mocker.patch(
        'app.dao.notifications_dao.dao_get_notification_by_reference',
        return_value=notification,
    )

    # Reference is used by many tests, can lead to trouble
    process_delivery_status(event=sample_delivery_status_result_message)

    assert mock_log_total_time.called_once_with(
        notification.id,
        notification.created_at,
        NOTIFICATION_DELIVERED,
        TWILIO_PROVIDER,
    )


@pytest.mark.serial
def test_process_delivery_status_no_status_reason_for_delivered(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
    sample_delivery_status_result_message,
):
    """
    When a notification is updated to "delivered" status, its "status_reason" should be set to
    the empty string.
    """

    # This test is marked "serial" because the reference is used by many tests.  Making it a random
    # value causes the test to fail.
    notification = sample_notification(
        template=sample_template(),
        reference='SMyyy',
        sent_at=datetime.now(timezone.utc),
        status=NOTIFICATION_SENT,
        status_reason='This is not the empty string.',
    )
    assert notification.reference == 'SMyyy'
    assert notification.status == NOTIFICATION_SENT
    assert notification.status_reason

    mocker.patch('app.celery.process_delivery_status_result_tasks._get_include_payload_status', returns=True)
    callback_mock = mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    process_delivery_status(event=sample_delivery_status_result_message)
    callback_mock.assert_called_once()

    notify_db_session.session.refresh(notification)
    assert notification.reference == 'SMyyy'
    assert notification.status == NOTIFICATION_DELIVERED
    assert notification.status_reason is None


def test_sms_status_update_notification_not_found(notify_api, mocker, sample_notification):
    mocker.patch(
        'app.celery.process_delivery_status_result_tasks.dao_update_sms_notification_delivery_status',
        side_effect=Exception,
    )

    notification = sample_notification(reference=str(uuid4()))
    sms_status = SmsStatusRecord(None, notification.reference, NOTIFICATION_DELIVERED, None, TWILIO_PROVIDER)
    with pytest.raises(NonRetryableException) as exc_info:
        sms_status_update(sms_status)
    assert 'Unable to update notification' in str(exc_info)


def test_sms_status_delivered_status_reason_set_to_none(notify_api, mocker, sample_notification):
    notification = sample_notification(status_reason='test_sms_status_delivered_status_update', reference=str(uuid4()))
    sms_status = SmsStatusRecord(
        None,
        notification.reference,
        NOTIFICATION_DELIVERED,
        'ignored reason',
        TWILIO_PROVIDER,
    )
    assert notification.status_reason == 'test_sms_status_delivered_status_update'

    sms_status_update(sms_status)
    notification = dao_get_notification_by_reference(notification.reference)
    assert notification.status_reason is None


def test_sms_status_provider_payload_set_to_none(notify_api, mocker, sample_notification):
    mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    notification = sample_notification(reference=str(uuid4()))
    sms_status = SmsStatusRecord(
        'not none',
        notification.reference,
        NOTIFICATION_DELIVERED,
        'ignored reason',
        PINPOINT_PROVIDER,
    )
    assert sms_status.payload is not None

    sms_status_update(sms_status)
    assert sms_status.payload is None


@pytest.mark.parametrize(
    'start_status, end_status',
    [
        *[(NOTIFICATION_CREATED, s) for s in _CREATED_UPDATES],
        *[(NOTIFICATION_SENDING, s) for s in _SENDING_UPDATES],
        *[(NOTIFICATION_PENDING, s) for s in _PENDING_UPDATES],
        *[(NOTIFICATION_SENT, s) for s in _SENT_UPDATES],
        *[(NOTIFICATION_DELIVERED, s) for s in _DELIVERED_UPDATES],
        *[(NOTIFICATION_TEMPORARY_FAILURE, s) for s in _TEMPORARY_FAILURE_UPDATES],
        *[(NOTIFICATION_PERMANENT_FAILURE, s) for s in _PERMANENT_FAILURE_UPDATES],
        *[(NOTIFICATION_TECHNICAL_FAILURE, s) for s in _TECHNICAL_FAILURE_UPDATES],
        *[(NOTIFICATION_PREFERENCES_DECLINED, s) for s in _PREFERENCES_DECLINED_UPDATES],
    ],
)
def test_sms_status_check_and_queue_called(notify_api, mocker, sample_notification, start_status, end_status):
    mock_callback = mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    # xdist has issues if the sample is built into the SmsStatusRecord, build separately
    notification = sample_notification(status=start_status, reference=str(uuid4()))
    sms_status = SmsStatusRecord('not none', notification.reference, end_status, 'ignored reason', PINPOINT_PROVIDER)

    sms_status_update(sms_status)
    mock_callback.assert_called_once()


@pytest.mark.parametrize(
    'start_status, end_status',
    [
        *[(NOTIFICATION_CREATED, s) for s in _CREATED_UPDATES],
        *[(NOTIFICATION_SENDING, s) for s in _SENDING_UPDATES],
        *[(NOTIFICATION_PENDING, s) for s in _PENDING_UPDATES],
        *[(NOTIFICATION_SENT, s) for s in _SENT_UPDATES],
        *[(NOTIFICATION_DELIVERED, s) for s in _DELIVERED_UPDATES],
        *[(NOTIFICATION_TEMPORARY_FAILURE, s) for s in _TEMPORARY_FAILURE_UPDATES],
        *[(NOTIFICATION_PERMANENT_FAILURE, s) for s in _PERMANENT_FAILURE_UPDATES],
        *[(NOTIFICATION_TECHNICAL_FAILURE, s) for s in _TECHNICAL_FAILURE_UPDATES],
        *[(NOTIFICATION_PREFERENCES_DECLINED, s) for s in _PREFERENCES_DECLINED_UPDATES],
    ],
)
def test_sms_status_check_and_queue_not_called(notify_api, mocker, sample_notification, start_status, end_status):
    mock_callback = mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    # xdist has issues if the sample is built into the SmsStatusRecord, build separately
    notification = sample_notification(status=start_status, reference=str(uuid4()))
    # Prevent the DB update so check_and_queue isn't called
    mocker.patch(
        'app.celery.process_delivery_status_result_tasks.dao_update_sms_notification_delivery_status',
        return_value=notification,
    )
    sms_status = SmsStatusRecord('not none', notification.reference, end_status, 'ignored reason', PINPOINT_PROVIDER)

    sms_status_update(sms_status)
    mock_callback.assert_not_called()


def test_sms_status_check_and_queue_exception(notify_api, mocker, sample_notification):
    mock_logger = mocker.patch('app.celery.process_delivery_status_result_tasks.current_app.logger.exception')
    mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task', side_effect=Exception)

    notification = sample_notification(reference=str(uuid4()))
    sms_status = SmsStatusRecord(
        'not none',
        notification.reference,
        NOTIFICATION_DELIVERED,
        'ignored reason',
        PINPOINT_PROVIDER,
    )

    # Exception is caught and not re-raised
    sms_status_update(sms_status)
    mock_logger.assert_called_once_with('Failed to check_and_queue_callback_task for notification: %s', notification.id)


@pytest.mark.parametrize(
    'provider, event_timestamp_in_ms, event_time_in_seconds',
    [
        (PINPOINT_PROVIDER, None, 0),
        (TWILIO_PROVIDER, None, 299),
        (PINPOINT_PROVIDER, 0, None),
        (TWILIO_PROVIDER, 4.99, None),  # This tolerance is tight for the test, may need to be 4.98
    ],
)
def test_get_notification_notification_not_found_retryable(
    notify_api,
    x_minutes_ago,
    mocker,
    provider,
    event_timestamp_in_ms,
    event_time_in_seconds,
):
    mock_dao_method = mocker.patch(
        'app.celery.process_delivery_status_result_tasks.dao_update_sms_notification_delivery_status'
    )
    if event_timestamp_in_ms is not None:
        # Get a datetime from x minutes ago and convert to epoch time in milliseconds
        event_timestamp_in_ms = x_minutes_ago(event_timestamp_in_ms).timestamp() * 1000
    with pytest.raises(AutoRetryException) as exc_info:
        _get_notification(str(uuid4()), provider, event_timestamp_in_ms, event_time_in_seconds)
    assert 'NoResultFound' in str(exc_info)

    # Make sure it didn't make it further into the method
    mock_dao_method.assert_not_called()


@pytest.mark.parametrize(
    'provider, event_timestamp_in_ms, event_time_in_seconds',
    [
        (PINPOINT_PROVIDER, None, 300),
        (TWILIO_PROVIDER, 5, None),
    ],
)
def test_get_notification_notification_not_found_nonretryable(
    notify_api,
    x_minutes_ago,
    mocker,
    provider,
    event_timestamp_in_ms,
    event_time_in_seconds,
):
    if event_timestamp_in_ms is not None:
        # Get a datetime from x minutes ago and convert to epoch time in milliseconds
        event_timestamp_in_ms = x_minutes_ago(event_timestamp_in_ms).timestamp() * 1000
    with pytest.raises(NonRetryableException) as exc_info:
        _get_notification(str(uuid4()), provider, event_timestamp_in_ms, event_time_in_seconds)
    assert 'Notification not found' in str(exc_info)


def test_get_notification_notification_multiple_found_nonretryable(
    notify_api,
    mocker,
):
    mocker.patch(
        'app.celery.process_delivery_status_result_tasks.dao_get_notification_by_reference',
        side_effect=MultipleResultsFound,
    )

    with pytest.raises(NonRetryableException) as exc_info:
        _get_notification(str(uuid4()), 'some provider', None, None)
    assert 'Multiple notifications found' in str(exc_info)


def test_get_notification_notification_found(
    notify_api,
    sample_notification,
):
    # Simple, but tests happy path of this function
    notification = sample_notification(reference=str(uuid4()))
    assert notification == _get_notification(notification.reference, 'some provider', None, None)


def test_get_notification_platform_status(notify_api, sample_delivery_status_result_message):
    # Happy path
    expected_sms_status_record = SmsStatusRecord(
        payload='RawDlrDoneDate=2303222338&SmsSid=SMxxx&SmsStatus=delivered&MessageStatus=delivered&To=%2B11111111111&MessageSid=SMyyy&AccountSid=ACzzz&From=%2B12223334444&ApiVersion=2010-04-01',
        reference='SMyyy',
        status='delivered',
        status_reason=None,
        provider='twilio',
        message_parts=1,
        price_millicents=0.0,
        provider_updated_at=datetime.strptime('2303222338', TwilioSMSClient.RAW_DLR_DONE_DATE_FMT),
    )
    assert expected_sms_status_record == get_notification_platform_status(
        TwilioSMSClient(), sample_delivery_status_result_message['message']['body']
    )


@pytest.mark.parametrize('exception', [KeyError, ValueError])
def test_get_notification_platform_status_exception(
    notify_api, mocker, sample_delivery_status_result_message, exception
):
    fake_twilio_client = TwilioSMSClient()
    with mocker.patch.object(fake_twilio_client, 'translate_delivery_status', side_effect=exception):
        with pytest.raises(NonRetryableException) as exc_info:
            get_notification_platform_status(
                fake_twilio_client, sample_delivery_status_result_message['message']['body']
            )
        assert UNABLE_TO_TRANSLATE in str(exc_info)


@pytest.mark.parametrize('include', [True, False])
def test_get_include_payload_status(notify_api, mocker, sample_notification, include):
    mocker.patch(
        'app.celery.process_delivery_status_result_tasks.dao_get_callback_include_payload_status', return_value=include
    )
    assert _get_include_payload_status(sample_notification()) == include


@pytest.mark.parametrize('exception', [AttributeError, TypeError])
def test_get_include_payload_status_exception(notify_api, mocker, sample_notification, exception):
    mocker.patch(
        'app.celery.process_delivery_status_result_tasks.dao_get_callback_include_payload_status', side_effect=exception
    )
    assert not _get_include_payload_status(sample_notification())
