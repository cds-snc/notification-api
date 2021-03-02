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
    ('_SMS.BUFFERED', 'SUCCESSFUL', NOTIFICATION_SENDING),
    ('_SMS.SUCCESS', 'DELIVERED', NOTIFICATION_DELIVERED),
    ('_SMS.FAILURE', 'INVALID', NOTIFICATION_TECHNICAL_FAILURE),
    ('_SMS.OPTOUT', 'DELIVERED', NOTIFICATION_DELIVERED)
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
    pinpoint_message_body = {
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
            "sender_request_id": reference,
            "campaign_activity_id": "1234",
            "origination_phone_number": "+15555555555",
            "destination_phone_number": "+15555555555",
            "record_status": record_status,
            "iso_country_code": "US",
            "treatment_id": "0",
            "number_of_message_parts": "1",
            "message_id": "1111-2222-3333",
            "message_type": "Transactional",
            "campaign_id": "12345"
        },
        "metrics": {
            "price_in_millicents_usd": 645.0
        },
        "awsAccountId": "123456789012"
    }

    return {
        'Type': 'Notification',
        'MessageId': '8e83c020-1234-1234-1234-92a8ee9baa0a',
        'TopicArn': 'arn:aws:sns:eu-west-1:12341234:ses_notifications',
        'Subject': None,
        'Message': json.dumps(pinpoint_message_body),
        'Timestamp': '2017-11-17T12:14:03.710Z',
        'SignatureVersion': '1',
        'Signature': '[REDACTED]',
        'SigningCertUrl': 'https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-[REDACTED].pem',
        'UnsubscribeUrl': 'https://sns.eu-west-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=[REACTED]',
        'MessageAttributes': {}
    }
