import pytest
from datetime import datetime

from app.clients.sms import SmsStatusRecord
from app.constants import NOTIFICATION_DELIVERED, NOTIFICATION_SENDING, PINPOINT_PROVIDER, STATUS_REASON_RETRYABLE
from app.celery.process_pinpoint_v2_receipt_tasks import process_pinpoint_v2_receipt_results


class TestProcessPinpointV2ReceiptResults:
    @pytest.fixture
    def sample_sms_status_record(self):
        """Fixture providing a sample SmsStatusRecord for testing"""
        return SmsStatusRecord(
            payload=None,
            reference='f47ac10b-58cc-4372-a567-0e02b2c3d479',
            status='delivered',
            status_reason=None,
            message_parts=1,
            provider=PINPOINT_PROVIDER,
            price_millicents=75,
            provider_updated_at=datetime(2024, 7, 31, 12, 0, 0, 0),
        )

    @pytest.fixture
    def retryable_sms_status_record(self):
        """Fixture providing a retryable SmsStatusRecord for testing"""
        return SmsStatusRecord(
            payload=None,
            reference='f47ac10b-58cc-4372-a567-0e02b2c3d479',
            status='temporary-failure',
            status_reason=STATUS_REASON_RETRYABLE,
            message_parts=1,
            provider=PINPOINT_PROVIDER,
            price_millicents=75,
            provider_updated_at=datetime(2024, 7, 31, 12, 0, 0, 0),
        )

    def test_process_receipt_results_calls_sms_status_update(
        self,
        mocker,
        sample_sms_status_record,
        sample_notification,
        notify_db_session,
    ):
        """Test that non-retryable status records call sms_status_update"""
        mock_sms_attempt_retry = mocker.patch('app.celery.process_pinpoint_v2_receipt_tasks.sms_attempt_retry')

        notification = sample_notification(status=NOTIFICATION_SENDING, reference=sample_sms_status_record.reference)

        event_timestamp = '1722427200000'

        process_pinpoint_v2_receipt_results(sample_sms_status_record, event_timestamp)

        notify_db_session.session.refresh(notification)
        assert notification.status == NOTIFICATION_DELIVERED

        mock_sms_attempt_retry.assert_not_called()

    def test_process_receipt_results_calls_sms_attempt_retry(self, mocker, retryable_sms_status_record):
        """Test that retryable status records call sms_attempt_retry"""
        mock_sms_status_update = mocker.patch('app.celery.process_pinpoint_v2_receipt_tasks.sms_status_update')
        mock_sms_attempt_retry = mocker.patch('app.celery.process_pinpoint_v2_receipt_tasks.sms_attempt_retry')

        event_timestamp = '1722427260000'

        process_pinpoint_v2_receipt_results(retryable_sms_status_record, event_timestamp)

        mock_sms_attempt_retry.assert_called_once_with(retryable_sms_status_record, event_timestamp)
        mock_sms_status_update.assert_not_called()
