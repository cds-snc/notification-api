import os
import pytest
from app.celery import provider_tasks
from app.celery.common import RETRIES_EXCEEDED
from app.celery.exceptions import NonRetryableException, AutoRetryException
from app.celery.provider_tasks import deliver_sms, deliver_email, deliver_sms_with_rate_limiting
from app.clients.email.aws_ses import AwsSesClientThrottlingSendRateException
from app.config import QueueNames
from app.exceptions import NotificationTechnicalFailureException, InvalidProviderException
from app.models import (
    EMAIL_TYPE,
    Notification,
    NOTIFICATION_CREATED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_TECHNICAL_FAILURE,
    SMS_TYPE,
)
from app.v2.errors import RateLimitError
from collections import namedtuple
from notifications_utils.recipients import InvalidEmailError, InvalidPhoneError
from uuid import uuid4


def test_should_have_decorated_tasks_functions():
    assert deliver_sms.__wrapped__.__name__ == 'deliver_sms'
    assert deliver_email.__wrapped__.__name__ == 'deliver_email'


def test_should_call_send_sms_to_provider_from_deliver_sms_task(
    mocker,
    sample_template,
    sample_notification,
):
    send_sms_to_provider = mocker.patch('app.delivery.send_to_providers.send_sms_to_provider')
    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template, status='sent')

    deliver_sms(notification.id)
    send_sms_to_provider.assert_called_once()
    assert send_sms_to_provider.call_args.args[0].id == notification.id
    assert send_sms_to_provider.call_args.args[1] is None


def test_should_add_to_retry_queue_if_notification_not_found_in_deliver_sms_task(mocker):
    send_sms_to_provider = mocker.patch('app.delivery.send_to_providers.send_sms_to_provider')

    notification_id = uuid4()
    with pytest.raises(Exception) as exc_info:
        deliver_sms(notification_id)

    assert exc_info.type is AutoRetryException
    send_sms_to_provider.assert_not_called()


def test_should_call_send_email_to_provider_from_deliver_email_task(
    mocker,
    sample_template,
    sample_notification,
):
    send_email_to_provider = mocker.patch('app.delivery.send_to_providers.send_email_to_provider')
    template = sample_template(template_type=EMAIL_TYPE)
    notification = sample_notification(template=template)

    deliver_email(notification.id)
    send_email_to_provider.assert_called_once()
    assert send_email_to_provider.call_args.args[0].id == notification.id


def test_should_add_to_retry_queue_if_notification_not_found_in_deliver_email_task(mocker):
    send_email_to_provider = mocker.patch('app.delivery.send_to_providers.send_email_to_provider')

    notification_id = uuid4()
    with pytest.raises(Exception) as exc_info:
        deliver_email(notification_id)

    assert exc_info.type is AutoRetryException
    send_email_to_provider.assert_not_called()


# DO THESE FOR THE 4 TYPES OF TASK


def test_should_go_into_technical_error_if_exceeds_retries_on_deliver_sms_task(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.delivery.send_to_providers.send_sms_to_provider', side_effect=Exception('EXPECTED'))
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})
    mocker.patch('app.celery.provider_tasks.can_retry', return_value=False)

    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(Exception) as exc_info:
        deliver_sms(notification.id)

    notify_db_session.session.refresh(notification)
    assert exc_info.type is NotificationTechnicalFailureException
    assert str(notification.id) in str(exc_info.value)
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == RETRIES_EXCEEDED


def test_should_technical_error_and_not_retry_if_invalid_email(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.delivery.send_to_providers.send_email_to_provider', side_effect=InvalidEmailError('bad email'))
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})

    template = sample_template(template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(Exception) as exc_info:
        deliver_email(notification.id)

    notify_db_session.session.refresh(notification)
    assert exc_info.type is NotificationTechnicalFailureException
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == 'Email address is in invalid format'


@pytest.mark.parametrize('exception', [NonRetryableException, InvalidPhoneError])
def test_should_queue_callback_task_if_permanent_failure_exception_is_thrown(
    mocker,
    sample_template,
    sample_notification,
    exception,
):
    mocker.patch(
        'app.celery.provider_tasks.send_to_providers.send_sms_to_provider',
        side_effect=exception,
    )

    mock_callback = mocker.patch('app.celery.common.check_and_queue_callback_task')
    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    deliver_sms(notification.id)

    mock_callback.assert_called_once()
    assert isinstance(mock_callback.call_args.args[0], Notification)
    assert mock_callback.call_args.args[0].id == notification.id


def test_should_mark_permanent_failure_when_utils_raises_invalid_phone_error(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch(
        'app.celery.provider_tasks.send_to_providers.send_sms_to_provider',
        side_effect=InvalidPhoneError,
    )

    callback_mocker = mocker.patch('app.celery.common.check_and_queue_callback_task')
    template = sample_template()
    notification = sample_notification(template=template)

    deliver_sms(notification.id)

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert callback_mocker.called_once


def test_should_mark_permanent_failure_when_celery_retries_exceeded(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    # NonRetryableException is a celery exception
    mocker.patch(
        'app.celery.provider_tasks.send_to_providers.send_sms_to_provider',
        side_effect=NonRetryableException,
    )

    callback_mocker = mocker.patch('app.celery.common.check_and_queue_callback_task')
    template = sample_template()
    notification = sample_notification(template=template)

    deliver_sms(notification.id)

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert callback_mocker.called_once


def test_should_go_into_technical_error_if_exceeds_retries_on_deliver_email_task(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.delivery.send_to_providers.send_email_to_provider', side_effect=Exception('EXPECTED'))
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})
    mocker.patch('app.celery.provider_tasks.can_retry', return_value=False)

    template = sample_template(template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(Exception) as exc_info:
        deliver_email(notification.id)

    notify_db_session.session.refresh(notification)
    assert exc_info.type is NotificationTechnicalFailureException
    assert str(notification.id) in str(exc_info.value)
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == RETRIES_EXCEEDED


def test_should_technical_error_and_not_retry_if_invalid_email_provider(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch(
        'app.delivery.send_to_providers.send_email_to_provider',
        side_effect=InvalidProviderException('invalid provider'),
    )
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})

    template = sample_template(template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(Exception) as exc_info:
        deliver_email(notification.id)

    notify_db_session.session.refresh(notification)
    assert exc_info.type is NotificationTechnicalFailureException
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == 'Email provider configuration invalid'


def test_should_queue_callback_task_if_technical_failure_exception_is_thrown(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch(
        'app.delivery.send_to_providers.send_email_to_provider',
        side_effect=InvalidProviderException('invalid provider'),
    )
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})
    callback_mocker = mocker.patch('app.celery.common.check_and_queue_callback_task')

    template = sample_template(template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(Exception) as exc_info:
        deliver_email(notification.id)

    notify_db_session.session.refresh(notification)
    assert exc_info.type is NotificationTechnicalFailureException
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == 'Email provider configuration invalid'
    assert callback_mocker.called_once


def test_should_technical_error_and_not_retry_if_invalid_sms_provider(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch(
        'app.delivery.send_to_providers.send_sms_to_provider', side_effect=InvalidProviderException('invalid provider')
    )
    mocker.patch('app.celery.provider_tasks.deliver_sms.retry')
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})

    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(NotificationTechnicalFailureException):
        deliver_sms(notification.id)

    notify_db_session.session.refresh(notification)
    assert provider_tasks.deliver_sms.retry.called is False
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == 'SMS provider configuration invalid'


def test_should_retry_and_log_exception(mocker, sample_template, sample_notification):
    mocker.patch(
        'app.delivery.send_to_providers.send_email_to_provider', side_effect=AwsSesClientThrottlingSendRateException
    )

    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(AutoRetryException) as exc_info:
        deliver_email(notification.id)

    assert exc_info.type is AutoRetryException
    assert notification.status == 'created'


def test_deliver_sms_with_rate_limiting_should_deliver_if_rate_limit_not_exceeded(
    mocker,
    sample_template,
    sample_notification,
):
    MockSmsSender = namedtuple('ServiceSmsSender', ['id', 'rate_limit', 'sms_sender'])
    sms_sender = MockSmsSender(id=uuid4(), rate_limit=50, sms_sender='+11111111111')

    mocker.patch('app.notifications.validators.check_sms_sender_over_rate_limit')
    send_sms_to_provider = mocker.patch('app.delivery.send_to_providers.send_sms_to_provider')
    mocker.patch(
        'app.celery.provider_tasks.dao_get_service_sms_sender_by_service_id_and_number', return_value=sms_sender
    )

    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    deliver_sms_with_rate_limiting(notification.id)
    send_sms_to_provider.assert_called_once()
    assert send_sms_to_provider.call_args.args[0].id == notification.id
    assert send_sms_to_provider.call_args.args[1] is None


def test_deliver_sms_with_rate_limiting_should_retry_if_rate_limit_exceeded(
    mocker,
    sample_template,
    sample_notification,
):
    MockSmsSender = namedtuple('ServiceSmsSender', ['id', 'rate_limit', 'rate_limit_interval'])
    sms_sender = MockSmsSender(id=uuid4(), rate_limit=50, rate_limit_interval=1)

    mocker.patch(
        'app.notifications.validators.check_sms_sender_over_rate_limit',
        side_effect=RateLimitError('Non Provider Exception', sms_sender.rate_limit),
    )

    mocker.patch('app.delivery.send_to_providers.send_sms_to_provider')
    mocker.patch(
        'app.celery.provider_tasks.dao_get_service_sms_sender_by_service_id_and_number', return_value=sms_sender
    )

    retry = mocker.patch('app.celery.provider_tasks.deliver_sms_with_rate_limiting.retry')
    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    deliver_sms_with_rate_limiting(notification.id)

    retry.assert_called_once_with(
        queue=QueueNames.RATE_LIMIT_RETRY,
        max_retries=None,
        countdown=sms_sender.rate_limit_interval / sms_sender.rate_limit,
    )


def test_deliver_sms_with_rate_limiting_should_retry_generic_exceptions(
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.celery.provider_tasks.send_to_providers.send_sms_to_provider', side_effect=Exception)
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})
    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(AutoRetryException) as exc_info:
        deliver_sms_with_rate_limiting(notification.id)

    assert exc_info.type is AutoRetryException


def test_deliver_sms_with_rate_limiting_max_retries_exceeded(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.celery.provider_tasks.send_to_providers.send_sms_to_provider', side_effect=Exception)
    mocker.patch('app.celery.provider_tasks.can_retry', return_value=False)
    mocker.patch.dict(os.environ, {'NOTIFICATION_FAILURE_REASON_ENABLED': 'True'})

    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(NotificationTechnicalFailureException) as exc_info:
        deliver_sms_with_rate_limiting(notification.id)

    notify_db_session.session.refresh(notification)
    assert exc_info.type is NotificationTechnicalFailureException
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == RETRIES_EXCEEDED
