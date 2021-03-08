import base64
import datetime
import json

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
    NOTIFICATION_SENT
)
from tests.app.db import create_notification


def test_passes_if_toggle_disabled(mocker, db_session):
    mock_toggle = mocker.patch('app.celery.process_pinpoint_receipt_tasks.is_feature_enabled', return_value=False)
    mock_dao = mocker.patch('app.celery.process_pinpoint_receipt_tasks.notifications_dao')

    process_pinpoint_receipt_tasks.process_pinpoint_results(response={})

    mock_toggle.assert_called_with(FeatureFlag.PINPOINT_RECEIPTS_ENABLED)
    mock_dao.dao_get_notification_by_reference.assert_not_called()
    mock_dao.notifications_dao.update_notification_status_by_id.assert_not_called()


@pytest.mark.parametrize('event_type, record_status, expected_notification_status', [
    ('_SMS.BUFFERED', 'SUCCESSFUL', NOTIFICATION_SENT),
    ('_SMS.SUCCESS', 'DELIVERED', NOTIFICATION_DELIVERED),
    ('_SMS.BUFFERED', 'PENDING', NOTIFICATION_SENDING),
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
    ('_SMS.OPTOUT', 'dummy', NOTIFICATION_PERMANENT_FAILURE)
])
def test_process_pinpoint_results_notification_final_status(
        mocker,
        db_session,
        sample_template,
        event_type,
        record_status,
        expected_notification_status
):
    mocker.patch('app.celery.process_pinpoint_receipt_tasks.is_feature_enabled', return_value=True)

    test_reference = 'sms-reference-1'
    create_notification(sample_template, reference=test_reference, sent_at=datetime.datetime.utcnow(), status='sending')
    process_pinpoint_receipt_tasks.process_pinpoint_results(
        response=pinpoint_notification_callback_record(
            reference=test_reference,
            event_type=event_type,
            record_status=record_status
        )
    )
    notification = notifications_dao.dao_get_notification_by_reference(test_reference)
    assert notification.status == expected_notification_status


def pinpoint_notification_callback_record(reference, event_type='_SMS.SUCCESS', record_status='DELIVERED'):
    pinpoint_message = {
        "event_type": event_type,
        "event_timestamp": 1553104954322,
        "arrival_timestamp": 1553104954064,
        "event_version": "3.1",
        "application": {
            "app_id": "123",
            "sdk": {}
        },
        "client": {
            "client_id": "123456789012"
        },
        "device": {
            "platform": {}
        },
        "session": {},
        "attributes": {
            "sender_request_id": 'e669df09-642b-4168-8563-3e5a4f9dcfbf',
            "campaign_activity_id": "1234",
            "origination_phone_number": "+15555555555",
            "destination_phone_number": "+15555555555",
            "record_status": record_status,
            "iso_country_code": "US",
            "treatment_id": "0",
            "number_of_message_parts": "1",
            "message_id": reference,
            "message_type": "Transactional",
            "campaign_id": "12345"
        },
        "metrics": {
            "price_in_millicents_usd": 645.0
        },
        "awsAccountId": "123456789012"
    }

    return {
        'Message': base64.b64encode(bytes(json.dumps(pinpoint_message), 'utf-8')).decode('utf-8')
    }
