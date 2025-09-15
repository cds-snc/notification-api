import pytest
from requests.exceptions import ConnectTimeout, ReadTimeout

from app.celery.exceptions import AutoRetryException
from app.celery.send_va_profile_notification_status_tasks import (
    check_and_queue_va_profile_notification_status_callback,
    send_notification_status_to_va_profile,
)
from app.constants import EMAIL_TYPE, SMS_TYPE


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
    @pytest.mark.parametrize('notification_type', [SMS_TYPE, EMAIL_TYPE])
    def test_can_send_notification_callback(self, mocker, sample_notification, notification_type):
        mock_send_notification_status_to_va_profile = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile'
        )

        notification = sample_notification(gen_type=notification_type)
        assert notification.notification_type == notification_type

        check_and_queue_va_profile_notification_status_callback(notification)

        mock_send_notification_status_to_va_profile.delay.assert_called_once()
