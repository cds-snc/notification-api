import base64
import json
from datetime import datetime, timezone
from uuid import uuid4

from app.clients.sms.aws_pinpoint import AwsPinpointClient
from app.dao import notifications_dao
from app.dao.notifications_dao import dao_update_notification_by_id
from app.models import Notification
import pytest

from app.celery.exceptions import NonRetryableException
from app.celery.process_pinpoint_receipt_tasks import process_pinpoint_results
from app.clients.sms import UNABLE_TO_TRANSLATE
from app.constants import (
    CARRIER_SMS_MAX_RETRIES,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    PINPOINT_PROVIDER,
    STATUS_REASON_BLOCKED,
    STATUS_REASON_INVALID_NUMBER,
    STATUS_REASON_UNDELIVERABLE,
)


@pytest.mark.parametrize(
    'event_type, record_status',
    [
        ('_SMS.FAILURE', k)
        for k, v in AwsPinpointClient._sms_record_status_mapping.items()
        if v[0] == NOTIFICATION_TEMPORARY_FAILURE
    ],
)
def test_process_pinpoint_results_should_attempt_retry(
    mocker,
    event_type,
    record_status,
    sample_notification,
):
    sample_notification(
        sent_at=datetime.now(timezone.utc),
        status=NOTIFICATION_SENDING,
    )

    sms_attempt_retry = mocker.patch('app.celery.process_pinpoint_receipt_tasks.sms_attempt_retry')
    sms_status_update = mocker.patch('app.celery.process_pinpoint_receipt_tasks.sms_status_update')

    process_pinpoint_results(
        response=pinpoint_notification_callback_record(event_type=event_type, record_status=record_status)
    )

    sms_attempt_retry.assert_called()
    sms_status_update.assert_not_called()


@pytest.mark.parametrize(
    'event_type, record_status',
    [
        ('_SMS.FAILURE', k)
        for k, v in AwsPinpointClient._sms_record_status_mapping.items()
        if v[0] != NOTIFICATION_TEMPORARY_FAILURE
    ],
)
def test_process_pinpoint_results_should_not_attempt_retry(
    mocker,
    event_type,
    record_status,
    sample_notification,
):
    sms_attempt_retry = mocker.patch('app.celery.process_pinpoint_receipt_tasks.sms_attempt_retry')
    sms_status_update = mocker.patch('app.celery.process_pinpoint_receipt_tasks.sms_status_update')

    sample_notification(
        sent_at=datetime.now(timezone.utc),
        status=NOTIFICATION_SENDING,
    )

    process_pinpoint_results(
        response=pinpoint_notification_callback_record(event_type=event_type, record_status=record_status)
    )

    sms_attempt_retry.assert_not_called()
    sms_status_update.assert_called()


@pytest.mark.parametrize(
    'event_type, record_status',
    [
        ('_SMS.FAILURE', k)
        for k, v in AwsPinpointClient._sms_record_status_mapping.items()
        if v[0] == NOTIFICATION_TEMPORARY_FAILURE
    ],
)
def test_process_pinpoint_results_should_queue_retry(
    mocker,
    sample_notification,
    event_type,
    record_status,
):
    mocker.patch('app.celery.process_delivery_status_result_tasks.update_sms_retry_count', return_value=1)
    mocked_send_to_queue = mocker.patch('app.notifications.process_notifications.send_notification_to_queue_delayed')

    notification = sample_notification(
        sent_at=datetime.now(timezone.utc),
        status=NOTIFICATION_SENDING,
    )

    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=notification.reference, event_type=event_type, record_status=record_status
        )
    )

    mocked_send_to_queue.assert_called()


@pytest.mark.parametrize('status', [NOTIFICATION_CREATED, NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE])
def test_process_pinpoint_results_should_not_queue_retry(
    mocker,
    status,
    sample_notification,
):
    sms_attempt_retry = mocker.patch('app.celery.process_pinpoint_receipt_tasks.sms_attempt_retry')
    mocked_send_to_queue = mocker.patch('app.notifications.process_notifications.send_notification_to_queue_delayed')

    sent_at_timestamp = datetime.now(timezone.utc) if status != NOTIFICATION_CREATED else None

    notification = sample_notification(
        sent_at=sent_at_timestamp,
        status=status,
    )

    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=notification.reference, event_type='_SMS.FAILURE', record_status='UNREACHABLE'
        )
    )

    sms_attempt_retry.assert_called()
    mocked_send_to_queue.assert_not_called()


@pytest.mark.parametrize(
    'event_type, record_status, expected_notification_status, expected_notification_status_reason',
    [
        ('_SMS.BUFFERED', 'PENDING', NOTIFICATION_SENDING, None),
        ('_SMS.BUFFERED', 'SUCCESSFUL', NOTIFICATION_SENDING, None),
        ('_SMS.SUCCESS', 'DELIVERED', NOTIFICATION_DELIVERED, None),
        ('_SMS.FAILURE', 'INVALID', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_INVALID_NUMBER),
        ('_SMS.FAILURE', 'UNREACHABLE', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        ('_SMS.FAILURE', 'UNKNOWN', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        ('_SMS.FAILURE', 'BLOCKED', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        ('_SMS.FAILURE', 'CARRIER_UNREACHABLE', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        ('_SMS.FAILURE', 'SPAM', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        ('_SMS.FAILURE', 'INVALID_MESSAGE', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        ('_SMS.FAILURE', 'CARRIER_BLOCKED', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        ('_SMS.FAILURE', 'TTL_EXPIRED', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        ('_SMS.FAILURE', 'MAX_PRICE_EXCEEDED', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        ('_SMS.FAILURE', 'OPTED_OUT', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        ('_SMS.OPTOUT', '', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
    ],
)
def test_process_pinpoint_results_notification_final_status(
    mocker,
    notify_db_session,
    event_type,
    record_status,
    expected_notification_status,
    expected_notification_status_reason,
    sample_notification,
):
    """
    Permissible event type and record status values are documented here:
        https://docs.aws.amazon.com/pinpoint/latest/developerguide/event-streams-data-sms.html

    An _SMS.OPTOUT event occurs when a veteran replies "STOP" to a text message.  An OPTED_OUT status occurs
    when Pinpoint receives input from Notify, but the Veteran has opted-out at the Pinpoint level.  This is
    different than Notify's communication item preferences.  If a veteran opts-out at that level, Pinpoint
    should never receive input trying to send a message to the opted-out veteran.

    Note: While NOTIFICATION_SENDING is not strictly a 'final' status, it is tested here in the context of the
    notification state after processing the event.

    Note: Retryable errors will result in a permanent failure if retry attempts have been exhausted.
    """

    mocker.patch('app.celery.process_delivery_status_result_tasks.update_sms_retry_count', return_value=1)
    mocker.patch('app.celery.process_delivery_status_result_tasks.can_retry_sms_request', return_value=False)
    mock_callback = mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    notification = sample_notification(
        sent_at=datetime.now(timezone.utc),
        status=NOTIFICATION_SENDING,
    )

    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=notification.reference, event_type=event_type, record_status=record_status
        )
    )

    notify_db_session.session.refresh(notification)

    assert notification.status == expected_notification_status

    if expected_notification_status == NOTIFICATION_PERMANENT_FAILURE:
        assert notification.status_reason == expected_notification_status_reason
    elif expected_notification_status == NOTIFICATION_DELIVERED:
        assert notification.status_reason is None

    if expected_notification_status != NOTIFICATION_SENDING:
        mock_callback.assert_called_once()


@pytest.mark.parametrize(
    'initial_status, event_type, record_status',
    [
        (NOTIFICATION_SENDING, '_SMS.BUFFERED', 'PENDING'),
        (NOTIFICATION_SENDING, '_SMS.BUFFERED', 'SUCCESSFUL'),
        (NOTIFICATION_DELIVERED, '_SMS.SUCCESS', 'DELIVERED'),
        (NOTIFICATION_PERMANENT_FAILURE, '_SMS.FAILURE', 'INVALID'),
        (NOTIFICATION_PERMANENT_FAILURE, '_SMS.FAILURE', 'BLOCKED'),
        (NOTIFICATION_PERMANENT_FAILURE, '_SMS.FAILURE', 'SPAM'),
        (NOTIFICATION_PERMANENT_FAILURE, '_SMS.FAILURE', 'INVALID_MESSAGE'),
        (NOTIFICATION_PERMANENT_FAILURE, '_SMS.FAILURE', 'CARRIER_BLOCKED'),
        (NOTIFICATION_PERMANENT_FAILURE, '_SMS.FAILURE', 'MAX_PRICE_EXCEEDED'),
        (NOTIFICATION_PERMANENT_FAILURE, '_SMS.FAILURE', 'OPTED_OUT'),
        (NOTIFICATION_PERMANENT_FAILURE, '_SMS.OPTOUT', ''),
    ],
)
def test_process_pinpoint_results_should_not_update_notification_status_if_unchanged(
    notify_db_session,
    mocker,
    sample_notification,
    x_minutes_ago,
    initial_status,
    event_type,
    record_status,
):
    mock_callback = mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    last_updated_at = x_minutes_ago(5)

    notification = sample_notification(updated_at=last_updated_at, status=initial_status)
    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=notification.reference, event_type=event_type, record_status=record_status
        )
    )

    notify_db_session.session.refresh(notification)

    assert notification.status == initial_status
    assert notification.updated_at == last_updated_at
    mock_callback.assert_not_called()


@pytest.mark.parametrize('status', [NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE])
def test_process_pinpoint_results_should_not_update_notification_status_to_sending_if_status_already_final(
    mocker,
    sample_template,
    status,
    sample_notification,
    x_minutes_ago,
):
    mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    test_reference = f'{uuid4()}-notification_status_to_sending_if_status_already_final'
    last_updated_at = x_minutes_ago(5)
    sample_notification(template=sample_template(), reference=test_reference, updated_at=last_updated_at, status=status)

    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference,
            event_type='_SMS.BUFFERED',
            record_status='PENDING',  # AWS equivalent of sending
        )
    )
    notification = notifications_dao.dao_get_notification_by_reference(test_reference)
    assert notification.status == status
    assert notification.updated_at == last_updated_at


@pytest.mark.parametrize(
    'status',
    [
        NOTIFICATION_CREATED,
        NOTIFICATION_SENDING,
        NOTIFICATION_TEMPORARY_FAILURE,
        NOTIFICATION_PERMANENT_FAILURE,
    ],
)
def test_process_pinpoint_results_delivered_clears_status_reason(
    mocker,
    notify_db_session,
    sample_template,
    status,
    sample_notification,
    x_minutes_ago,
):
    mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    test_reference = f'{uuid4()}-update_notification_status_with_delivered'
    last_updated_at = x_minutes_ago(5)
    template = sample_template()
    sample_notification(
        template=template,
        reference=test_reference,
        sent_at=last_updated_at,
        updated_at=last_updated_at,
        status=status,
        status_reason='any status reason',
    )
    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference,
            event_type='_SMS.SUCCESS',
            record_status='DELIVERED',  # Pinpoint-specific
        )
    )
    notification = notifications_dao.dao_get_notification_by_reference(test_reference)
    assert notification.status == NOTIFICATION_DELIVERED
    assert notification.status_reason is None
    assert notification.updated_at != last_updated_at


def pinpoint_notification_callback_record(
    reference=f'{uuid4()}',
    event_type='_SMS.SUCCESS',
    record_status='DELIVERED',
    number_of_message_parts=1,
    price=645.0,
):
    pinpoint_message = {
        'event_type': event_type,
        'event_timestamp': 1553104954322,
        'arrival_timestamp': 1553104954064,
        'event_version': '3.1',
        'application': {'app_id': '123', 'sdk': {}},
        'client': {'client_id': '123456789012'},
        'device': {'platform': {}},
        'session': {},
        'attributes': {
            'sender_request_id': 'e669df09-642b-4168-8563-3e5a4f9dcfbf',
            'campaign_activity_id': '1234',
            'origination_phone_number': '+15555555555',
            'destination_phone_number': '+15555555555',
            'record_status': record_status,
            'iso_country_code': 'US',
            'treatment_id': '0',
            'number_of_message_parts': number_of_message_parts,
            'message_id': reference,
            'message_type': 'Transactional',
            'campaign_id': '12345',
        },
        'metrics': {
            'price_in_millicents_usd': price,
        },
        'awsAccountId': '123456789012',
    }

    return {'Message': base64.b64encode(bytes(json.dumps(pinpoint_message), 'utf-8')).decode('utf-8')}


def test_wt_process_pinpoint_callback_should_log_total_time(
    mocker,
    client,
    sample_template,
    sample_notification,
):
    mock_log_total_time = mocker.patch('app.celery.common.log_notification_total_time')
    mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    ref = str(uuid4())
    # Reference is used by many tests, can lead to trouble
    notification = sample_notification(template=sample_template(), status=NOTIFICATION_SENDING, reference=ref)
    # Mock db call
    mocker.patch(
        'app.dao.notifications_dao.dao_get_notification_by_reference',
        return_value=notification,
    )

    process_pinpoint_results(pinpoint_notification_callback_record(reference=ref))

    assert mock_log_total_time.called_once_with(
        notification.id,
        notification.created_at,
        NOTIFICATION_DELIVERED,
        PINPOINT_PROVIDER,
    )


@pytest.mark.parametrize('exception', [json.decoder.JSONDecodeError, ValueError, TypeError, KeyError])
def test_process_pinpoint_callback_message_parse_exception(
    notify_api,
    mocker,
    exception,
):
    # Mock b64 decode so we can raise exceptions in the try block
    mocker.patch('app.celery.process_pinpoint_receipt_tasks.json.loads', side_effect=exception)

    with pytest.raises(NonRetryableException) as exc_info:
        process_pinpoint_results(pinpoint_notification_callback_record(reference=str(uuid4())))
    assert UNABLE_TO_TRANSLATE in str(exc_info)


@pytest.mark.parametrize(
    'event_type, record_status',
    [
        ('_SMS.DELIVERED', 'SUCCESSFUL'),
        ('_SMS.FAILURE', 'UNREACHABLE'),  # STATUS_REASON_RETRYABLE
        ('_SMS.FAILURE', 'INVALID'),  # NOTIFICATION_PERMANENT_FAILURE
    ],
)
def test_process_pinpoint_results_should_update_cost_in_millicents(
    notify_db_session,
    mocker,
    event_type,
    record_status,
    sample_notification,
):
    initial_cost = 1000
    additional_cost = 100

    notification: Notification = sample_notification(
        sent_at=datetime.now(timezone.utc), status=NOTIFICATION_SENDING, cost_in_millicents=initial_cost
    )

    assert notification.cost_in_millicents == initial_cost

    mocker.patch('app.celery.process_delivery_status_result_tasks.update_sms_retry_count', return_value=1)
    mocker.patch('app.celery.process_delivery_status_result_tasks.get_sms_retry_delay', return_value=60)
    mocker.patch('app.notifications.process_notifications.send_notification_to_queue_delayed')

    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            notification.reference, event_type, record_status, price=additional_cost
        )
    )

    notify_db_session.session.refresh(notification)

    assert notification.cost_in_millicents == initial_cost + additional_cost


@pytest.mark.parametrize(
    'event_type, record_status',
    [
        ('_SMS.FAILURE', 'UNREACHABLE'),
        ('_SMS.FAILURE', 'UNKNOWN'),
        ('_SMS.FAILURE', 'CARRIER_UNREACHABLE'),
        ('_SMS.FAILURE', 'TTL_EXPIRED'),
    ],
)
def test_process_pinpoint_results_should_update_cost_in_millicents_retries_exhausted(
    notify_db_session,
    mocker,
    event_type,
    record_status,
    sample_notification,
):
    initial_cost = 1000
    additional_cost = 100

    notification: Notification = sample_notification(
        sent_at=datetime.now(timezone.utc), status=NOTIFICATION_SENDING, cost_in_millicents=initial_cost
    )

    assert notification.cost_in_millicents == initial_cost

    mocker.patch(
        'app.celery.process_delivery_status_result_tasks.update_sms_retry_count',
        return_value=CARRIER_SMS_MAX_RETRIES + 1,
    )
    mocked_send_to_queue = mocker.patch('app.notifications.process_notifications.send_notification_to_queue_delayed')

    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            notification.reference, event_type, record_status, price=additional_cost
        )
    )

    notify_db_session.session.refresh(notification)

    mocked_send_to_queue.assert_not_called()
    assert notification.cost_in_millicents == initial_cost + additional_cost


@pytest.mark.parametrize(
    'initial_status, event_type, record_status',
    [
        (NOTIFICATION_SENDING, '_SMS.BUFFERED', 'PENDING'),
        (NOTIFICATION_SENDING, '_SMS.BUFFERED', 'SUCCESSFUL'),
    ],
)
def test_process_pinpoint_results_should_not_update_cost_in_millicents(
    notify_db_session,
    mocker,
    initial_status,
    event_type,
    record_status,
    sample_notification,
):
    notification: Notification = sample_notification(
        sent_at=datetime.now(timezone.utc),
        status=initial_status,
    )

    assert notification.cost_in_millicents == 0

    mocker.patch('app.celery.process_delivery_status_result_tasks.update_sms_retry_count', return_value=1)
    mocker.patch('app.celery.process_delivery_status_result_tasks.get_sms_retry_delay', return_value=60)
    mocked_send_to_queue = mocker.patch('app.notifications.process_notifications.send_notification_to_queue_delayed')

    process_pinpoint_results(
        response=pinpoint_notification_callback_record(notification.reference, event_type, record_status)
    )

    notify_db_session.session.refresh(notification)

    mocked_send_to_queue.assert_not_called()
    assert notification.cost_in_millicents == 0


def test_process_pinpoint_results_sequence_retry_delivered(
    mocker,
    sample_notification,
    notify_db_session,
):
    """
    Test processing a Pinpoint SMS stream event.  Messages long enough to require multiple segments only
    result in one event that contains the aggregate cost.
    """
    mocker.patch('app.celery.process_delivery_status_result_tasks.update_sms_retry_count', return_value=1)
    mocker.patch('app.celery.process_delivery_status_result_tasks.get_sms_retry_delay', return_value=60)
    mocked_send_to_queue = mocker.patch('app.notifications.process_notifications.send_notification_to_queue_delayed')

    notification = sample_notification(sent_at=datetime.now(timezone.utc), status=NOTIFICATION_SENDING)

    assert notification.segments_count == 0, 'This is the default.'
    assert notification.cost_in_millicents == 0.0, 'This is the default.'

    cost_per_attempt = 1000.0

    # Receiving a _SMS.FAILURE+UNKNOWN event first should trigger retry
    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=notification.reference,
            event_type='_SMS.FAILURE',
            record_status='UNKNOWN',
            number_of_message_parts=6,
            price=cost_per_attempt,
        )
    )

    mocked_send_to_queue.assert_called()

    notify_db_session.session.refresh(notification)

    assert notification.status == NOTIFICATION_CREATED
    assert notification.segments_count == 6
    assert notification.cost_in_millicents == cost_per_attempt
    assert notification.status_reason is None
    assert notification.reference is None

    # simulate successful send to provider
    notification = dao_update_notification_by_id(
        notification_id=notification.id,
        status=NOTIFICATION_SENDING,
        status_reason=None,
        reference=str(uuid4()),
        sent_at=datetime.now(timezone.utc),
    )

    # A subsequent _SMS.SUCCESS+DELIVERED event should process as delivered with summed cost
    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=notification.reference,
            event_type='_SMS.SUCCESS',
            record_status='DELIVERED',
            number_of_message_parts=6,
            price=cost_per_attempt,
        )
    )

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_DELIVERED
    assert notification.segments_count == 6
    # total cost of original failed attempt and subsequent retry
    assert notification.cost_in_millicents == cost_per_attempt * 2
    assert notification.status_reason is None


def test_process_pinpoint_results_sequence_retry_stale_reference(
    mocker,
    sample_notification,
    notify_db_session,
):
    """
    Test processing a Pinpoint SMS stream event.  Messages long enough to require multiple segments only
    result in one event that contains the aggregate cost.
    """
    mocker.patch('app.celery.process_delivery_status_result_tasks.update_sms_retry_count', return_value=1)
    mocker.patch('app.celery.process_delivery_status_result_tasks.get_sms_retry_delay', return_value=60)
    mocked_send_to_queue = mocker.patch('app.notifications.process_notifications.send_notification_to_queue_delayed')

    notification = sample_notification(sent_at=datetime.now(timezone.utc), status=NOTIFICATION_SENDING)

    original_reference = notification.reference

    assert notification.segments_count == 0, 'This is the default.'
    assert notification.cost_in_millicents == 0.0, 'This is the default.'

    cost_per_attempt = 1000.0

    # Receiving a _SMS.FAILURE+UNKNOWN event first should trigger retry
    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=notification.reference,
            event_type='_SMS.FAILURE',
            record_status='UNKNOWN',
            number_of_message_parts=6,
            price=cost_per_attempt,
        )
    )

    mocked_send_to_queue.assert_called()

    notify_db_session.session.refresh(notification)

    assert notification.status == NOTIFICATION_CREATED
    assert notification.segments_count == 6
    assert notification.cost_in_millicents == cost_per_attempt
    assert notification.status_reason is None
    assert notification.reference is None

    # simulate successful send to provider
    notification = dao_update_notification_by_id(
        notification_id=notification.id,
        status=NOTIFICATION_SENDING,
        status_reason=None,
        reference=str(uuid4()),
        sent_at=datetime.now(timezone.utc),
    )

    # A subsequent out-of-order/late _SMS.SUCCESS+DELIVERED event with stale reference should throw NonRetryableException
    # The original reference was cleared for requeue so the notification can not be found by reference
    # The cost of the attempt has already been recorded by the earlier retry attempt
    # The out-of-order/late events can lead to duplicate delivery attempts but this is unavoidable
    with pytest.raises(NonRetryableException):
        process_pinpoint_results(
            response=pinpoint_notification_callback_record(
                reference=original_reference,
                event_type='_SMS.SUCCESS',
                record_status='DELIVERED',
                number_of_message_parts=6,
                price=cost_per_attempt,
            )
        )

    notify_db_session.session.refresh(notification)

    assert notification.status == NOTIFICATION_SENDING
    assert notification.cost_in_millicents == cost_per_attempt
    assert notification.status_reason is None
    assert notification.reference is not original_reference

    # A subsequent _SMS.SUCCESS+DELIVERED event should process as delivered with summed cost
    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=notification.reference,
            event_type='_SMS.SUCCESS',
            record_status='DELIVERED',
            number_of_message_parts=6,
            price=cost_per_attempt,
        )
    )

    notify_db_session.session.refresh(notification)

    assert notification.status == NOTIFICATION_DELIVERED
    assert notification.segments_count == 6
    # total cost of original failed attempt and subsequent retry
    # out-of-order/late success event is not double counted
    assert notification.cost_in_millicents == cost_per_attempt * 2
    assert notification.status_reason is None


def test_process_pinpoint_results_notification_final_status_personalisation(
    mocker,
    notify_db_session,
    sample_template,
    sample_notification,
):
    mock_callback = mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    test_reference = str(uuid4())
    template = sample_template(content='Hello ((name))')
    notification = sample_notification(
        template=template,
        reference=test_reference,
        sent_at=datetime.now(timezone.utc),
        status=NOTIFICATION_SENDING,
        status_reason='just because',
        personalisation={'name': 'Bob'},
    )
    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference, event_type='_SMS.SUCCESS', record_status='DELIVERED'
        )
    )
    notify_db_session.session.refresh(notification)
    assert notification.personalisation == {'name': '<redacted>'}
    mock_callback.assert_called_once()
