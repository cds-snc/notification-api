import base64
import json
from datetime import datetime

from flask import url_for
import pytest
from freezegun import freeze_time

from app.clients.sms import SmsStatusRecord
from app.constants import PINPOINT_PROVIDER
from app.feature_flags import FeatureFlag


class TestPinpointV2DeliveryStatus:
    @pytest.fixture
    def pinpoint_sms_voice_v2_data(self):
        """Fixture providing sample PinpointSMSVoiceV2 data for testing"""
        raw_records = [
            {
                'data': {
                    'eventType': 'TEXT_SUCCESSFUL',
                    'eventVersion': '1.0',
                    'eventTimestamp': 1722427200000,
                    'isFinal': True,
                    'originationPhoneNumber': '+12065550152',
                    'destinationPhoneNumber': '+15551234567',
                    'isoCountryCode': 'US',
                    'mcc': '310',
                    'mnc': '800',
                    'messageId': 'test-message-id-123',
                    'messageRequestTimestamp': 1722427199000,
                    'messageEncoding': 'GSM',
                    'messageType': 'TRANSACTIONAL',
                    'messageStatus': 'DELIVERED',
                    'messageStatusDescription': 'Message has been accepted by phone carrier',
                    'context': {'source': 'test-source'},
                    'totalMessageParts': 1,
                    'totalMessagePrice': 0.075,
                    'totalCarrierFee': 0.0,
                }
            },
            {
                'data': {
                    'eventType': 'TEXT_SUCCESSFUL',
                    'eventVersion': '1.0',
                    'eventTimestamp': 1722427260000,
                    'isFinal': True,
                    'originationPhoneNumber': '+12065550152',
                    'destinationPhoneNumber': '+15559876543',
                    'isoCountryCode': 'US',
                    'mcc': '310',
                    'mnc': '800',
                    'messageId': 'test-message-id-456',
                    'messageRequestTimestamp': 1722427259000,
                    'messageEncoding': 'GSM',
                    'messageType': 'TRANSACTIONAL',
                    'messageStatus': 'DELIVERED',
                    'messageStatusDescription': 'Message has been accepted by phone carrier',
                    'context': {'source': 'test-source'},
                    'totalMessageParts': 1,
                    'totalMessagePrice': 0.075,
                    'totalCarrierFee': 0.0,
                }
            },
        ]

        # Create encoded records with only the 'data' field base64 encoded
        encoded_records = []
        for record in raw_records:
            encoded_record = record.copy()
            encoded_record['data'] = base64.b64encode(json.dumps(record['data']).encode('utf-8')).decode('utf-8')
            encoded_records.append(encoded_record)

        return {'raw_records': raw_records, 'sns_payload': {'records': encoded_records}}

    @freeze_time('2025-08-07 10:30:00')
    def test_post_delivery_status_no_records(self, client, mocker):
        mocker.patch('app.delivery_status.rest.process_pinpoint_v2_receipt_results.apply_async')
        mocker.patch('app.delivery_status.rest.get_notification_platform_status')

        request_payload = {'records': [], 'requestId': 'test-request-123'}
        response = client.post(
            url_for('pinpoint_v2.handler'), json=request_payload, headers=[('X-Amz-Firehose-Access-Key', 'dev')]
        )

        assert response.status_code == 200
        assert response.json == {'requestId': 'test-request-123', 'timestamp': '1754562600000'}

    @freeze_time('2025-08-07 10:30:00')
    def test_post_delivery_status_multiple_records(self, client, mocker, pinpoint_sms_voice_v2_data):
        """Test the happy path with expected PinpointSMSVoiceV2 data from firehose"""

        mock_celery_task = mocker.patch('app.delivery_status.rest.process_pinpoint_v2_receipt_results.apply_async')

        mock_feature_flag = mocker.Mock(FeatureFlag)
        mock_feature_flag.value = 'PINPOINT_SMS_VOICE_V2'
        mocker.patch('app.feature_flags.os.getenv', return_value='True')

        request_payload = pinpoint_sms_voice_v2_data['sns_payload']
        request_payload['requestId'] = 'test-request-456'

        response = client.post(
            url_for('pinpoint_v2.handler'), json=request_payload, headers=[('X-Amz-Firehose-Access-Key', 'dev')]
        )

        expected_record_1 = SmsStatusRecord(
            payload=None,
            reference='test-message-id-123',
            status='delivered',
            status_reason=None,
            message_parts=1,
            provider=PINPOINT_PROVIDER,
            price_millicents=75,
            provider_updated_at=datetime(2024, 7, 31, 12, 0, 0, 0),
        )

        expected_record_2 = SmsStatusRecord(
            payload=None,
            reference='test-message-id-456',
            status='delivered',
            status_reason=None,
            message_parts=1,
            provider=PINPOINT_PROVIDER,
            price_millicents=75,
            provider_updated_at=datetime(2024, 7, 31, 12, 1, 0, 0),
        )

        assert response.status_code == 200
        assert response.json == {'requestId': 'test-request-456', 'timestamp': '1754562600000'}

        assert mock_celery_task.call_count == 2

        first_call_args = mock_celery_task.call_args_list[0][0][0]
        assert first_call_args[0] == expected_record_1
        assert first_call_args[1] == 1722427200000

        second_call_args = mock_celery_task.call_args_list[1][0][0]
        assert second_call_args[0] == expected_record_2
        assert second_call_args[1] == 1722427260000

    @freeze_time('2025-08-07 10:30:00')
    def test_post_delivery_status_with_validation_errors(self, client, mocker, pinpoint_sms_voice_v2_data, caplog):
        """Test that validation errors for individual records don't stop processing of other records"""

        mock_feature_flag = mocker.Mock(FeatureFlag)
        mock_feature_flag.value = 'PINPOINT_SMS_VOICE_V2'
        mocker.patch('app.feature_flags.os.getenv', return_value='True')

        mock_celery_task = mocker.patch('app.delivery_status.rest.process_pinpoint_v2_receipt_results.apply_async')
        mock_logger = mocker.patch('app.delivery_status.rest.current_app.logger')

        # Create a mix of valid and invalid records
        records = [
            # Valid record 1
            {
                'data': base64.b64encode(
                    json.dumps(
                        {
                            'eventType': 'TEXT_SUCCESSFUL',
                            'eventVersion': '1.0',
                            'eventTimestamp': 1722427200000,
                            'isFinal': True,
                            'originationPhoneNumber': '+12065550152',
                            'destinationPhoneNumber': '+15551234567',
                            'isoCountryCode': 'US',
                            'mcc': '310',
                            'mnc': '800',
                            'messageId': 'test-message-id-123',
                            'messageRequestTimestamp': 1722427199000,
                            'messageEncoding': 'GSM',
                            'messageType': 'TRANSACTIONAL',
                            'messageStatus': 'DELIVERED',
                            'messageStatusDescription': 'Message has been accepted by phone carrier',
                            'context': {'source': 'test-source'},
                            'totalMessageParts': 1,
                            'totalMessagePrice': 0.075,
                            'totalCarrierFee': 0.0,
                        }
                    ).encode('utf-8')
                ).decode('utf-8')
            },
            # Invalid record - missing eventType and messageId
            {
                'data': base64.b64encode(
                    json.dumps(
                        {
                            'eventVersion': '1.0',
                            'eventTimestamp': 1722427260000,
                            'isFinal': True,
                            # Missing eventType and messageId - this will cause validation to fail
                        }
                    ).encode('utf-8')
                ).decode('utf-8')
            },
            # Valid record 2
            {
                'data': base64.b64encode(
                    json.dumps(
                        {
                            'eventType': 'TEXT_SUCCESSFUL',
                            'eventVersion': '1.0',
                            'eventTimestamp': 1722427320000,
                            'isFinal': True,
                            'originationPhoneNumber': '+12065550152',
                            'destinationPhoneNumber': '+15559876543',
                            'isoCountryCode': 'US',
                            'mcc': '310',
                            'mnc': '800',
                            'messageId': 'test-message-id-789',
                            'messageRequestTimestamp': 1722427319000,
                            'messageEncoding': 'GSM',
                            'messageType': 'TRANSACTIONAL',
                            'messageStatus': 'DELIVERED',
                            'messageStatusDescription': 'Message has been accepted by phone carrier',
                            'context': {'source': 'test-source'},
                            'totalMessageParts': 1,
                            'totalMessagePrice': 0.075,
                            'totalCarrierFee': 0.0,
                        }
                    ).encode('utf-8')
                ).decode('utf-8')
            },
        ]

        request_payload = {'records': records, 'requestId': 'test-request-789'}

        response = client.post(
            url_for('pinpoint_v2.handler'), json=request_payload, headers=[('X-Amz-Firehose-Access-Key', 'dev')]
        )

        assert response.status_code == 200
        assert response.json == {'requestId': 'test-request-789', 'timestamp': '1754562600000'}

        # Should have processed 2 valid records, skipped 1 invalid
        assert mock_celery_task.call_count == 2

        # Check that error was logged with unknown messageId
        assert mock_logger.error.call_count == 1
        assert mock_logger.error.call_args[0] == (
            'Validation for PinpointV2 delivery-status records failed: %s | Error: %s',
            'unknown messageId',
            'Invalid PinpointSMSVoiceV2 message format, unable to translate delivery status',
        )

    @freeze_time('2025-08-07 10:30:00')
    def test_post_delivery_status_with_decoding_errors(self, client, mocker):
        """Test that records with decoding errors are skipped and logged"""

        mock_celery_task = mocker.patch('app.delivery_status.rest.process_pinpoint_v2_receipt_results.apply_async')
        mock_get_notification_platform_status = mocker.patch(
            'app.delivery_status.rest.get_notification_platform_status'
        )
        mock_logger = mocker.patch('app.delivery_status.rest.current_app.logger')

        records = [
            # Record missing 'data' field
            {'other_field': 'value'},
            # Record with invalid base64
            {'data': 'invalid-base64'},
            # Record with valid base64 but invalid JSON
            {'data': base64.b64encode(b'invalid json').decode('utf-8')},
        ]

        request_payload = {'records': records, 'requestId': 'test-request-123'}

        response = client.post(
            url_for('pinpoint_v2.handler'), json=request_payload, headers=[('X-Amz-Firehose-Access-Key', 'dev')]
        )

        assert response.status_code == 200
        assert response.json == {'requestId': 'test-request-123', 'timestamp': '1754562600000'}

        assert mock_logger.error.call_count == 3

        error_calls = mock_logger.error.call_args_list

        assert error_calls[0][0][0] == 'Failed to decode PinpointV2 delivery-status record data: %s | Error: %s'
        assert error_calls[0][0][1] == {'other_field': 'value'}

        assert error_calls[1][0][0] == 'Failed to decode PinpointV2 delivery-status record data: %s | Error: %s'
        assert error_calls[1][0][1] == {'data': 'invalid-base64'}
        assert 'Invalid base64-encoded string' in str(error_calls[1][0][2]) or 'Incorrect padding' in str(
            error_calls[1][0][2]
        )

        assert error_calls[2][0][0] == 'Failed to decode PinpointV2 delivery-status record data: %s | Error: %s'
        assert error_calls[2][0][1] == {'data': base64.b64encode(b'invalid json').decode('utf-8')}
        assert 'Expecting value' in str(error_calls[2][0][2])

        assert mock_celery_task.call_count == 0
        assert mock_get_notification_platform_status.call_count == 0
