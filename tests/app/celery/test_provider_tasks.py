import os
import uuid
from collections import namedtuple

import pytest
from notifications_utils.recipients import InvalidEmailError


import app
from app.celery import provider_tasks
from app.celery.common import RETRIES_EXCEEDED
from app.celery.exceptions import NonRetryableException, AutoRetryException
from app.celery.provider_tasks import deliver_sms, deliver_email, deliver_sms_with_rate_limiting
from app.clients.email.aws_ses import AwsSesClientThrottlingSendRateException
from app.config import QueueNames
from app.exceptions import NotificationTechnicalFailureException, InvalidProviderException
from app.models import NOTIFICATION_PERMANENT_FAILURE
from app.v2.errors import RateLimitError


def test_should_have_decorated_tasks_functions():
    assert deliver_sms.__wrapped__.__name__ == 'deliver_sms'
    assert deliver_email.__wrapped__.__name__ == 'deliver_email'


def test_should_call_send_sms_to_provider_from_deliver_sms_task(
        sample_notification,
        mocker):
    mocker.patch('app.delivery.send_to_providers.send_sms_to_provider')

    deliver_sms(sample_notification.id)
    app.delivery.send_to_providers.send_sms_to_provider.assert_called_with(sample_notification, None)


def test_should_add_to_retry_queue_if_notification_not_found_in_deliver_sms_task(notify_db_session, mocker):
    mocker.patch('app.delivery.send_to_providers.send_sms_to_provider')

    notification_id = app.create_uuid()
    with pytest.raises(Exception) as exc_info:
        deliver_sms(notification_id)

    assert exc_info.type is AutoRetryException
    app.delivery.send_to_providers.send_sms_to_provider.assert_not_called()


def test_should_call_send_email_to_provider_from_deliver_email_task(sample_notification, mocker):
    mocker.patch('app.delivery.send_to_providers.send_email_to_provider')

    deliver_email(sample_notification.id)
    app.delivery.send_to_providers.send_email_to_provider.assert_called_with(sample_notification)


def test_should_add_to_retry_queue_if_notification_not_found_in_deliver_email_task(mocker):
    mocker.patch('app.delivery.send_to_providers.send_email_to_provider')

    notification_id = app.create_uuid()
    with pytest.raises(Exception) as exc_info:
        deliver_email(notification_id)

    assert exc_info.type is AutoRetryException
    app.delivery.send_to_providers.send_email_to_provider.assert_not_called()


# DO THESE FOR THE 4 TYPES OF TASK

def test_should_go_into_technical_error_if_exceeds_retries_on_deliver_sms_task(sample_notification, mocker):
    mocker.patch('app.delivery.send_to_providers.send_sms_to_provider', side_effect=Exception("EXPECTED"))
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})
    mocker.patch('app.celery.provider_tasks.can_retry', return_value=False)

    with pytest.raises(Exception) as exc_info:
        deliver_sms(sample_notification.id)

    assert exc_info.type is NotificationTechnicalFailureException
    assert str(sample_notification.id) in str(exc_info.value)
    assert sample_notification.status == 'technical-failure'
    assert sample_notification.status_reason == RETRIES_EXCEEDED


def test_should_technical_error_and_not_retry_if_invalid_email(sample_notification, mocker):
    mocker.patch('app.delivery.send_to_providers.send_email_to_provider', side_effect=InvalidEmailError('bad email'))
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})

    with pytest.raises(Exception) as exc_info:
        deliver_email(sample_notification.id)

    assert exc_info.type is NotificationTechnicalFailureException
    assert sample_notification.status == 'technical-failure'
    assert sample_notification.status_reason == 'Email address is in invalid format'


def test_should_queue_callback_task_if_non_retryable_exception_is_thrown(sample_notification, mocker):
    mocker.patch(
        'app.celery.provider_tasks.send_to_providers.send_sms_to_provider',
        side_effect=NonRetryableException('Exception')
    )

    mock_callback = mocker.patch('app.celery.provider_tasks.check_and_queue_callback_task')

    deliver_sms(sample_notification.id)

    assert sample_notification.status == NOTIFICATION_PERMANENT_FAILURE
    mock_callback.assert_called_once_with(sample_notification)


def test_should_go_into_technical_error_if_exceeds_retries_on_deliver_email_task(sample_notification, mocker):
    mocker.patch('app.delivery.send_to_providers.send_email_to_provider', side_effect=Exception("EXPECTED"))
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})
    mocker.patch('app.celery.provider_tasks.can_retry', return_value=False)

    with pytest.raises(Exception) as exc_info:
        deliver_email(sample_notification.id)

    assert exc_info.type is NotificationTechnicalFailureException
    assert str(sample_notification.id) in str(exc_info.value)
    assert sample_notification.status == 'technical-failure'
    assert sample_notification.status_reason == RETRIES_EXCEEDED


def test_should_technical_error_and_not_retry_if_invalid_email_provider(sample_notification, mocker):
    mocker.patch(
        'app.delivery.send_to_providers.send_email_to_provider',
        side_effect=InvalidProviderException('invalid provider')
    )
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})

    with pytest.raises(Exception) as exc_info:
        deliver_email(sample_notification.id)

    assert exc_info.type is NotificationTechnicalFailureException
    assert sample_notification.status == 'technical-failure'
    assert sample_notification.status_reason == 'Email provider configuration invalid'


def test_should_technical_error_and_not_retry_if_invalid_sms_provider(sample_notification, mocker):
    mocker.patch(
        'app.delivery.send_to_providers.send_sms_to_provider',
        side_effect=InvalidProviderException('invalid provider')
    )
    mocker.patch('app.celery.provider_tasks.deliver_sms.retry')
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})

    with pytest.raises(NotificationTechnicalFailureException):
        deliver_sms(sample_notification.id)

    assert provider_tasks.deliver_sms.retry.called is False
    assert sample_notification.status == 'technical-failure'
    assert sample_notification.status_reason == 'SMS provider configuration invalid'


def test_should_retry_and_log_exception(sample_notification, mocker):
    mocker.patch('app.delivery.send_to_providers.send_email_to_provider',
                 side_effect=AwsSesClientThrottlingSendRateException)
    with pytest.raises(AutoRetryException) as exc_info:
        deliver_email(sample_notification.id)

    assert exc_info.type is AutoRetryException
    assert sample_notification.status == 'created'


def test_deliver_sms_with_rate_limiting_should_deliver_if_rate_limit_not_exceeded(sample_notification, mocker):
    MockSmsSender = namedtuple('ServiceSmsSender', ['id', 'rate_limit', 'sms_sender'])
    sms_sender = MockSmsSender(id=uuid.uuid4(), rate_limit=50, sms_sender='+11111111111')

    mocker.patch(
        'app.notifications.validators.check_sms_sender_over_rate_limit'
    )
    send_to_provider = mocker.patch('app.delivery.send_to_providers.send_sms_to_provider')
    mocker.patch(
        'app.celery.provider_tasks.dao_get_service_sms_sender_by_service_id_and_number',
        return_value=sms_sender
    )

    deliver_sms_with_rate_limiting(sample_notification.id)

    send_to_provider.assert_called_once_with(sample_notification, None)


def test_deliver_sms_with_rate_limiting_should_retry_if_rate_limit_exceeded(sample_notification, mocker):
    MockSmsSender = namedtuple('ServiceSmsSender', ['id', 'rate_limit', 'rate_limit_interval'])
    sms_sender = MockSmsSender(id=uuid.uuid4(), rate_limit=50, rate_limit_interval=1)

    mocker.patch(
        'app.notifications.validators.check_sms_sender_over_rate_limit',
        side_effect=RateLimitError('Non Provider Exception', sms_sender.rate_limit)
    )

    mocker.patch('app.delivery.send_to_providers.send_sms_to_provider')
    mocker.patch(
        'app.celery.provider_tasks.dao_get_service_sms_sender_by_service_id_and_number',
        return_value=sms_sender
    )

    retry = mocker.patch('app.celery.provider_tasks.deliver_sms_with_rate_limiting.retry')

    deliver_sms_with_rate_limiting(sample_notification.id)

    retry.assert_called_once_with(
        queue=QueueNames.RATE_LIMIT_RETRY, max_retries=None,
        countdown=sms_sender.rate_limit_interval / sms_sender.rate_limit
    )
