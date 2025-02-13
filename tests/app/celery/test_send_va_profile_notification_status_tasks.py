from datetime import datetime

import pytest
from requests.exceptions import ConnectTimeout, ReadTimeout

from app.celery.exceptions import AutoRetryException
from app.celery.send_va_profile_notification_status_tasks import (
    check_and_queue_va_profile_notification_status_callback,
    send_notification_status_to_va_profile,
)
from app.constants import EMAIL_TYPE, SMS_TYPE
from app.feature_flags import FeatureFlag
from app.models import Notification


class TestSendNotificationStatusToVAProfile:
    mock_sms_notification_data = {
        'id': '2e9e6920-4f6f-4cd5-9e16-fc306fe23867',
        'reference': None,
        'to': '(732)846-6666',
        'status': 'delivered',
        'status_reason': '',
        'created_at': '2024-07-25T10:00:00.0',
        'completed_at': '2024-07-25T11:00:00.0',
        'sent_at': '2024-07-25T11:00:00.0',
        'notification_type': SMS_TYPE,
        'sent_by': 'twilio',
        'service_name': 'VA Notify',
    }

    mock_email_notification_data = {
        'id': '2e9e6920-4f6f-4cd5-9e16-fc306fe23867',
        'reference': None,
        'to': 'test@email.com',
        'status': 'delivered',
        'status_reason': '',
        'created_at': '2024-07-25T10:00:00.0',
        'completed_at': '2024-07-25T11:00:00.0',
        'sent_at': '2024-07-25T11:00:00.0',
        'notification_type': EMAIL_TYPE,
        'provider': 'ses',
        'service_name': 'VA Notify',
    }

    @pytest.mark.parametrize('notification_data', [mock_email_notification_data, mock_sms_notification_data])
    def test_ut_send_notification_status_to_va_profile(self, mocker, notification_data):
        mock_va_profile_client_send_status = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.va_profile_client.send_va_profile_notification_status'
        )

        send_notification_status_to_va_profile(notification_data)

        mock_va_profile_client_send_status.assert_called_once_with(notification_data)

    @pytest.mark.parametrize('notification_data', [mock_email_notification_data, mock_sms_notification_data])
    def test_ut_send_notification_status_to_va_profile_raises_auto_retry_exception(self, mocker, notification_data):
        mock_va_profile_client_send_status = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.va_profile_client.send_va_profile_notification_status',
            side_effect=[ConnectTimeout, ReadTimeout],
        )

        with pytest.raises(AutoRetryException):
            send_notification_status_to_va_profile(notification_data)

        mock_va_profile_client_send_status.assert_called_once()


class TestCheckAndQueueVANotificationCallback:
    def test_feature_flag_enabled(self, mocker, sample_notification):
        mock_feature_enabled = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.is_feature_enabled', return_value=True
        )
        mock_send_notification_status_to_va_profile = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile'
        )

        notification = sample_notification()

        check_and_queue_va_profile_notification_status_callback(notification)

        mock_feature_enabled.assert_called_once_with(FeatureFlag.VA_PROFILE_SMS_STATUS_ENABLED)
        mock_send_notification_status_to_va_profile.delay.assert_called_once()

    @pytest.mark.parametrize('notification_type', [SMS_TYPE, EMAIL_TYPE])
    def test_sms_feature_flag_disabled(self, mocker, sample_notification, notification_type):
        mock_feature_enabled = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.is_feature_enabled', return_value=False
        )
        mock_send_notification_status_to_va_profile = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile'
        )

        notification = sample_notification(gen_type=notification_type)
        assert notification.notification_type == notification_type

        check_and_queue_va_profile_notification_status_callback(notification)

        mock_feature_enabled.assert_called_once_with(FeatureFlag.VA_PROFILE_SMS_STATUS_ENABLED)

        if notification.notification_type == SMS_TYPE:
            mock_send_notification_status_to_va_profile.delay.assert_not_called()
        else:
            mock_send_notification_status_to_va_profile.delay.assert_called_once()
