import pytest

from app.celery.common import RETRIES_EXCEEDED
from app.celery.exceptions import NonRetryableException, AutoRetryException
from app.celery.provider_tasks import deliver_sms, deliver_email, deliver_sms_with_rate_limiting
from app.clients.email.aws_ses import AwsSesClientThrottlingSendRateException
from app.config import QueueNames
from app.constants import EMAIL_TYPE, NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_TECHNICAL_FAILURE, SMS_TYPE
from app.exceptions import (
    NotificationTechnicalFailureException,
    InvalidProviderException,
)
from app.models import Notification
from app.v2.errors import RateLimitError
from collections import namedtuple
from notifications_utils.field import NullValueForNonConditionalPlaceholderException
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
    with pytest.raises(AutoRetryException):
        deliver_sms(notification_id)

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
    with pytest.raises(AutoRetryException):
        deliver_email(notification_id)

    send_email_to_provider.assert_not_called()


# DO THESE FOR THE 4 TYPES OF TASK


def test_should_go_into_technical_error_if_exceeds_retries_on_deliver_sms_task(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.delivery.send_to_providers.send_sms_to_provider', side_effect=Exception('EXPECTED'))
    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.provider_tasks.check_and_queue_callback_task',
    )
    mocker.patch('app.celery.provider_tasks.can_retry', return_value=False)

    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(NotificationTechnicalFailureException) as exc_info:
        deliver_sms(notification.id)

    notify_db_session.session.refresh(notification)
    assert str(notification.id) in str(exc_info.value)
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == RETRIES_EXCEEDED
    mocked_check_and_queue_callback_task.assert_called_once()


def test_should_technical_error_and_not_retry_if_invalid_email(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.delivery.send_to_providers.send_email_to_provider', side_effect=InvalidEmailError('bad email'))
    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.provider_tasks.check_and_queue_callback_task',
    )

    template = sample_template(template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(NotificationTechnicalFailureException):
        deliver_email(notification.id)

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == 'Email address is in invalid format'
    mocked_check_and_queue_callback_task.assert_called_once()


@pytest.mark.parametrize(
    'exception,expected_to_raise',
    (
        (NonRetryableException, None),
        (InvalidPhoneError, NotificationTechnicalFailureException),
    ),
)
def test_should_queue_callback_task_if_permanent_failure_exception_is_thrown(
    mocker,
    sample_template,
    sample_notification,
    exception,
    expected_to_raise,
):
    mocker.patch(
        'app.celery.provider_tasks.send_to_providers.send_sms_to_provider',
        side_effect=exception,
    )

    mock_callback = mocker.patch('app.celery.common.check_and_queue_callback_task')
    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    if expected_to_raise:
        with pytest.raises(expected_to_raise):
            deliver_sms(notification.id)
    else:
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

    with pytest.raises(NotificationTechnicalFailureException):
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
    callback_mocker.assert_called_once()


def test_should_go_into_technical_error_if_exceeds_retries_on_deliver_email_task(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.delivery.send_to_providers.send_email_to_provider', side_effect=Exception('EXPECTED'))
    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.provider_tasks.check_and_queue_callback_task',
    )
    mocker.patch('app.celery.provider_tasks.can_retry', return_value=False)

    template = sample_template(template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(NotificationTechnicalFailureException) as exc_info:
        deliver_email(notification.id)

    notify_db_session.session.refresh(notification)
    assert str(notification.id) in str(exc_info.value)
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == RETRIES_EXCEEDED
    mocked_check_and_queue_callback_task.assert_called_once()


@pytest.mark.parametrize(
    'exception, status_reason',
    (
        (InvalidProviderException, 'Email provider configuration invalid'),
        (NullValueForNonConditionalPlaceholderException, 'VA Notify non-retryable technical error'),
        (AttributeError, 'VA Notify non-retryable technical error'),
        (RuntimeError, 'VA Notify non-retryable technical error'),
    ),
)
def test_should_technical_error_and_not_retry_if_invalid_email_provider(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
    exception,
    status_reason,
):
    mocker.patch(
        'app.delivery.send_to_providers.send_email_to_provider',
        side_effect=exception,
    )
    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.provider_tasks.check_and_queue_callback_task',
    )
    callback_mocker = mocker.patch('app.celery.common.check_and_queue_callback_task')

    template = sample_template(template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(NotificationTechnicalFailureException):
        deliver_email(notification.id)

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == status_reason
    assert mocked_check_and_queue_callback_task.called_once or callback_mocker.called_once


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
    callback_mocker = mocker.patch('app.celery.common.check_and_queue_callback_task')

    template = sample_template(template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(NotificationTechnicalFailureException):
        deliver_email(notification.id)

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == 'Email provider configuration invalid'
    assert callback_mocker.called_once


@pytest.mark.parametrize(
    'exception, status_reason',
    (
        (InvalidProviderException, 'SMS provider configuration invalid'),
        (NullValueForNonConditionalPlaceholderException, 'VA Notify non-retryable technical error'),
        (AttributeError, 'VA Notify non-retryable technical error'),
        (RuntimeError, 'VA Notify non-retryable technical error'),
    ),
)
def test_should_technical_error_and_not_retry_if_invalid_sms_provider(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
    exception,
    status_reason,
):
    mocker.patch('app.delivery.send_to_providers.send_sms_to_provider', side_effect=exception)
    callback_mocker = mocker.patch('app.celery.common.check_and_queue_callback_task')
    retry_mocker = mocker.patch('app.celery.provider_tasks.deliver_sms.retry')

    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(NotificationTechnicalFailureException):
        deliver_sms(notification.id)

    notify_db_session.session.refresh(notification)
    retry_mocker.assert_not_called()
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == status_reason
    callback_mocker.assert_called_once()


def test_should_retry_and_log_exception(mocker, sample_template, sample_notification):
    mocker.patch(
        'app.delivery.send_to_providers.send_email_to_provider', side_effect=AwsSesClientThrottlingSendRateException
    )

    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(AutoRetryException):
        deliver_email(notification.id)

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
        queue=QueueNames.RETRY,
        max_retries=None,
        countdown=sms_sender.rate_limit_interval / sms_sender.rate_limit,
    )


def test_deliver_sms_with_rate_limiting_should_retry_generic_exceptions(
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.celery.provider_tasks.send_to_providers.send_sms_to_provider', side_effect=Exception)
    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(AutoRetryException):
        deliver_sms_with_rate_limiting(notification.id)


def test_deliver_sms_with_rate_limiting_max_retries_exceeded(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.celery.provider_tasks.send_to_providers.send_sms_to_provider', side_effect=Exception)
    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.provider_tasks.check_and_queue_callback_task',
    )
    mocker.patch('app.celery.provider_tasks.can_retry', return_value=False)

    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(NotificationTechnicalFailureException):
        deliver_sms_with_rate_limiting(notification.id)

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_TECHNICAL_FAILURE
    assert notification.status_reason == RETRIES_EXCEEDED
    mocked_check_and_queue_callback_task.assert_called_once()
