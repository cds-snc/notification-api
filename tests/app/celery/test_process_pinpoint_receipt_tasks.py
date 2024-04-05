import base64
import datetime
import json
from uuid import uuid4

import pytest

from app.celery import process_pinpoint_receipt_tasks
from app.dao import notifications_dao
from app.feature_flags import FeatureFlag
from app.models import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
)


def test_passes_if_toggle_disabled(mocker):
    mock_toggle = mocker.patch('app.celery.process_pinpoint_receipt_tasks.is_feature_enabled', return_value=False)
    mock_update_notification_status_by_id = mocker.patch(
        'app.celery.process_pinpoint_receipt_tasks.update_notification_status_by_id'
    )
    mock_dao_get_notification_by_reference = mocker.patch(
        'app.celery.process_pinpoint_receipt_tasks.dao_get_notification_by_reference'
    )

    process_pinpoint_receipt_tasks.process_pinpoint_results(response={})

    mock_toggle.assert_called_with(FeatureFlag.PINPOINT_RECEIPTS_ENABLED)
    mock_dao_get_notification_by_reference.assert_not_called()
    mock_update_notification_status_by_id.assert_not_called()


@pytest.mark.parametrize(
    'event_type, record_status, expected_notification_status',
    [
        ('_SMS.BUFFERED', 'SUCCESSFUL', NOTIFICATION_DELIVERED),
        ('_SMS.SUCCESS', 'DELIVERED', NOTIFICATION_DELIVERED),
        ('_SMS.FAILURE', 'INVALID', NOTIFICATION_TECHNICAL_FAILURE),
        ('_SMS.FAILURE', 'UNREACHABLE', NOTIFICATION_TEMPORARY_FAILURE),
        ('_SMS.FAILURE', 'UNKNOWN', NOTIFICATION_TEMPORARY_FAILURE),
        ('_SMS.FAILURE', 'BLOCKED', NOTIFICATION_PERMANENT_FAILURE),
        ('_SMS.FAILURE', 'CARRIER_UNREACHABLE', NOTIFICATION_TEMPORARY_FAILURE),
        ('_SMS.FAILURE', 'SPAM', NOTIFICATION_PERMANENT_FAILURE),
        ('_SMS.FAILURE', 'INVALID_MESSAGE', NOTIFICATION_TECHNICAL_FAILURE),
        ('_SMS.FAILURE', 'CARRIER_BLOCKED', NOTIFICATION_PERMANENT_FAILURE),
        ('_SMS.FAILURE', 'TTL_EXPIRED', NOTIFICATION_TEMPORARY_FAILURE),
        ('_SMS.FAILURE', 'MAX_PRICE_EXCEEDED', NOTIFICATION_TECHNICAL_FAILURE),
        ('_SMS.OPTOUT', 'dummy', NOTIFICATION_PERMANENT_FAILURE),
    ],
)
def test_process_pinpoint_results_notification_final_status(
    mocker,
    sample_template,
    event_type,
    record_status,
    expected_notification_status,
    sample_notification,
):
    mocker.patch('app.celery.process_pinpoint_receipt_tasks.is_feature_enabled', return_value=True)
    mock_callback = mocker.patch('app.celery.process_pinpoint_receipt_tasks.check_and_queue_callback_task')

    test_reference = str(uuid4())
    template = sample_template()
    sample_notification(
        template=template, reference=test_reference, sent_at=datetime.datetime.utcnow(), status='sending'
    )
    process_pinpoint_receipt_tasks.process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference, event_type=event_type, record_status=record_status
        )
    )
    notification = notifications_dao.dao_get_notification_by_reference(test_reference)
    assert notification.status == expected_notification_status
    mock_callback.assert_called_once()


def test_process_pinpoint_results_should_not_update_notification_status_if_unchanged(
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.celery.process_pinpoint_receipt_tasks.is_feature_enabled', return_value=True)
    mock_callback = mocker.patch('app.celery.process_pinpoint_receipt_tasks.check_and_queue_callback_task')
    update_notification_status = mocker.patch(
        'app.celery.process_pinpoint_receipt_tasks.update_notification_status_by_id'
    )

    test_reference = f'{uuid4()}-sms-reference-1'
    template = sample_template()
    sample_notification(
        template=template, reference=test_reference, sent_at=datetime.datetime.utcnow(), status='sending'
    )
    process_pinpoint_receipt_tasks.process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference, event_type='_SMS.BUFFERED', record_status='PENDING'
        )
    )
    notification = notifications_dao.dao_get_notification_by_reference(test_reference)
    assert notification.status == NOTIFICATION_SENDING

    update_notification_status.assert_not_called()
    mock_callback.assert_not_called()


@pytest.mark.parametrize(
    'status', [NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_TECHNICAL_FAILURE]
)
def test_process_pinpoint_results_should_not_update_notification_status_if_status_already_final(
    mocker,
    sample_template,
    status,
    sample_notification,
):
    mocker.patch('app.celery.process_pinpoint_receipt_tasks.is_feature_enabled', return_value=True)
    mock_callback = mocker.patch('app.celery.process_pinpoint_receipt_tasks.check_and_queue_callback_task')
    update_notification_status = mocker.patch(
        'app.celery.process_pinpoint_receipt_tasks.update_notification_status_by_id'
    )

    test_reference = f'{uuid4()}=sms-reference-1'
    template = sample_template()
    sample_notification(template=template, reference=test_reference, sent_at=datetime.datetime.utcnow(), status=status)
    process_pinpoint_receipt_tasks.process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference, event_type='_SMS.BUFFERED', record_status='PENDING'
        )
    )
    notification = notifications_dao.dao_get_notification_by_reference(test_reference)
    assert notification.status == status

    update_notification_status.assert_not_called()
    mock_callback.assert_not_called()


def test_process_pinpoint_results_segments_and_price_buffered_first(
    mocker,
    sample_template,
    sample_notification,
    notify_db_session,
):
    """
    Test process a Pinpoint SMS stream event.  Messages long enough to require multiple segments only
    result in one event that contains the aggregate cost.
    """

    mocker.patch('app.celery.process_pinpoint_receipt_tasks.is_feature_enabled', return_value=True)
    test_reference = f'{uuid4()}=sms-reference-1'
    template = sample_template()
    notification = sample_notification(
        template=template, reference=test_reference, sent_at=datetime.datetime.utcnow(), status='sending'
    )
    assert notification.segments_count == 0, 'This is the default.'
    assert notification.cost_in_millicents == 0.0, 'This is the default.'

    # Receiving a _SMS.BUFFERED+SUCCESSFUL event first should update the notification.
    process_pinpoint_receipt_tasks.process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference,
            event_type='_SMS.BUFFERED',
            record_status='SUCCESSFUL',
            number_of_message_parts=6,
            price=4986.0,
        )
    )

    notification = notifications_dao.dao_get_notification_by_reference(test_reference)
    notify_db_session.session.refresh(notification)

    assert notification.segments_count == 6
    assert notification.cost_in_millicents == 4986.0

    # A subsequent _SMS.SUCCESS+DELIVERED event should not alter the segments and price columns.
    process_pinpoint_receipt_tasks.process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference,
            event_type='_SMS.SUCCESS',
            record_status='DELIVERED',
            number_of_message_parts=6,
            price=4986.0,
        )
    )

    notification = notifications_dao.dao_get_notification_by_reference(test_reference)
    assert notification.segments_count == 6
    assert notification.cost_in_millicents == 4986.0


def test_process_pinpoint_results_segments_and_price_success_first(mocker, sample_template, sample_notification):
    """
    Test process a Pinpoint SMS stream event.  Messages long enough to require multiple segments only
    result in one event that contains the aggregate cost.

    Receiving a _SMS.SUCCESS+DELIVERED without any preceeding _SMS.BUFFERED event should update the
    notification.
    """

    mocker.patch('app.celery.process_pinpoint_receipt_tasks.is_feature_enabled', return_value=True)
    test_reference = f'{uuid4()}-sms-reference-1'
    template = sample_template()
    sample_notification(
        template=template, reference=test_reference, sent_at=datetime.datetime.utcnow(), status='sending'
    )

    process_pinpoint_receipt_tasks.process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference,
            event_type='_SMS.SUCCESS',
            record_status='DELIVERED',
            number_of_message_parts=4,
            price=2986.0,
        )
    )

    notification = notifications_dao.dao_get_notification_by_reference(test_reference)
    assert notification.segments_count == 4
    assert notification.cost_in_millicents == 2986.0


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
    mocker.patch('app.celery.service_callback_tasks.check_and_queue_callback_task')

    # Reference is used by many tests, can lead to trouble
    notification = sample_notification(template=sample_template(), status='sending', reference='SMyyy')
    # Mock db call
    mocker.patch(
        'app.dao.notifications_dao.dao_get_notification_by_reference',
        return_value=notification,
    )

    process_pinpoint_receipt_tasks.process_pinpoint_results(pinpoint_notification_callback_record())

    assert mock_log_total_time.called_once_with(
        notification.id,
        notification.created_at,
        NOTIFICATION_DELIVERED,
        'pinpoint',
    )
