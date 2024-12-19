import base64
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.celery.exceptions import NonRetryableException
from app.celery.process_pinpoint_receipt_tasks import process_pinpoint_results
from app.clients.sms import UNABLE_TO_TRANSLATE
from app.constants import (
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    PINPOINT_PROVIDER,
    STATUS_REASON_BLOCKED,
    STATUS_REASON_RETRYABLE,
    STATUS_REASON_UNDELIVERABLE,
)
from app.dao import notifications_dao


@pytest.mark.parametrize(
    'event_type, record_status, expected_notification_status, expected_notification_status_reason',
    [
        ('_SMS.BUFFERED', 'SUCCESSFUL', NOTIFICATION_DELIVERED, None),
        ('_SMS.SUCCESS', 'DELIVERED', NOTIFICATION_DELIVERED, None),
        ('_SMS.FAILURE', 'INVALID', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        ('_SMS.FAILURE', 'UNREACHABLE', NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        ('_SMS.FAILURE', 'UNKNOWN', NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        ('_SMS.FAILURE', 'BLOCKED', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        ('_SMS.FAILURE', 'CARRIER_UNREACHABLE', NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        ('_SMS.FAILURE', 'SPAM', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        ('_SMS.FAILURE', 'INVALID_MESSAGE', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        ('_SMS.FAILURE', 'CARRIER_BLOCKED', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        ('_SMS.FAILURE', 'TTL_EXPIRED', NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        ('_SMS.FAILURE', 'MAX_PRICE_EXCEEDED', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        ('_SMS.FAILURE', 'OPTED_OUT', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        ('_SMS.OPTOUT', '', NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
    ],
)
def test_process_pinpoint_results_notification_final_status(
    mocker,
    sample_template,
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
    """

    mock_callback = mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    test_reference = str(uuid4())
    template = sample_template()
    sample_notification(
        template=template,
        reference=test_reference,
        sent_at=datetime.now(timezone.utc),
        status=NOTIFICATION_SENDING,
        status_reason='just because',
    )
    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference, event_type=event_type, record_status=record_status
        )
    )
    notification = notifications_dao.dao_get_notification_by_reference(test_reference)
    assert notification.status == expected_notification_status

    if expected_notification_status == NOTIFICATION_PERMANENT_FAILURE:
        assert notification.status_reason == expected_notification_status_reason
    elif expected_notification_status == NOTIFICATION_DELIVERED:
        assert notification.status_reason is None

    mock_callback.assert_called_once()


def test_process_pinpoint_results_should_not_update_notification_status_if_unchanged(
    mocker,
    sample_template,
    sample_notification,
    x_minutes_ago,
):
    mock_callback = mocker.patch('app.celery.process_delivery_status_result_tasks.check_and_queue_callback_task')

    test_reference = f'{uuid4()}-test_process_pinpoint_results_should_not_update_notification_status_if_unchanged'
    template = sample_template()
    last_updated_at = x_minutes_ago(5)

    sample_notification(
        template=template, reference=test_reference, updated_at=last_updated_at, status=NOTIFICATION_SENDING
    )
    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference, event_type='_SMS.BUFFERED', record_status='PENDING'
        )
    )
    notification = notifications_dao.dao_get_notification_by_reference(test_reference)
    assert notification.status == NOTIFICATION_SENDING
    assert notification.updated_at == last_updated_at
    mock_callback.assert_not_called()


@pytest.mark.parametrize(
    'status', [NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_PERMANENT_FAILURE]
)
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


def test_process_pinpoint_results_segments_and_price_buffered_first(
    mocker,
    sample_template,
    sample_notification,
    notify_db_session,
):
    """
    Test processing a Pinpoint SMS stream event.  Messages long enough to require multiple segments only
    result in one event that contains the aggregate cost.
    """

    test_reference = f'{uuid4()}=sms-reference-1'
    template = sample_template()
    notification = sample_notification(
        template=template, reference=test_reference, sent_at=datetime.now(timezone.utc), status=NOTIFICATION_SENDING
    )
    assert notification.segments_count == 0, 'This is the default.'
    assert notification.cost_in_millicents == 0.0, 'This is the default.'

    # Receiving a _SMS.BUFFERED+SUCCESSFUL event first should update the notification.
    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference,
            event_type='_SMS.BUFFERED',
            record_status='SUCCESSFUL',
            number_of_message_parts=6,
            price=4986.0,
        )
    )

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_DELIVERED
    assert notification.segments_count == 6
    assert notification.cost_in_millicents == 4986.0
    assert notification.status_reason is None

    # A subsequent _SMS.SUCCESS+DELIVERED event should not alter the segments and price columns.
    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference,
            event_type='_SMS.SUCCESS',
            record_status='DELIVERED',
            number_of_message_parts=6,
            price=4986.0,
        )
    )

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_DELIVERED
    assert notification.segments_count == 6
    assert notification.cost_in_millicents == 4986.0
    assert notification.status_reason is None


def test_process_pinpoint_results_segments_and_price_success_first(
    notify_db_session, mocker, sample_template, sample_notification
):
    """
    Test processing a Pinpoint SMS stream event.  Messages long enough to require multiple segments only
    result in one event that contains the aggregate cost.

    Receiving a _SMS.SUCCESS+DELIVERED without any preceeding _SMS.BUFFERED event should update the
    notification.
    """

    test_reference = f'{uuid4()}-sms-reference-1'
    template = sample_template()
    notification = sample_notification(
        template=template, reference=test_reference, sent_at=datetime.now(timezone.utc), status=NOTIFICATION_SENDING
    )

    process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference,
            event_type='_SMS.SUCCESS',
            record_status='DELIVERED',
            number_of_message_parts=4,
            price=2986.0,
        )
    )

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_DELIVERED
    assert notification.segments_count == 4
    assert notification.cost_in_millicents == 2986.0
    assert notification.status_reason is None


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
