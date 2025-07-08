from unittest.mock import patch
from uuid import uuid4

import botocore
from requests import HTTPError, Response
from requests.exceptions import ConnectTimeout, RequestException
from app.mobile_app.mobile_app_types import MobileAppType
import pytest

from app.celery.exceptions import AutoRetryException, NonRetryableException
from app.celery.provider_tasks import (
    deliver_email,
    deliver_push,
    deliver_sms,
    deliver_sms_with_rate_limiting,
    _handle_delivery_failure,
)
from app.clients.email.aws_ses import AwsSesClient, AwsSesClientThrottlingSendRateException
from app.constants import (
    EMAIL_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_PERMANENT_FAILURE,
    SMS_TYPE,
    STATUS_REASON_BLOCKED,
    STATUS_REASON_UNDELIVERABLE,
    STATUS_REASON_UNREACHABLE,
)
from app.exceptions import (
    NotificationTechnicalFailureException,
    InvalidProviderException,
)
from app.models import Notification
from app.v2.errors import RateLimitError
from collections import namedtuple
from notifications_utils.field import NullValueForNonConditionalPlaceholderException
from notifications_utils.recipients import InvalidEmailError, InvalidPhoneError


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


def test_should_go_into_permanent_error_if_exceeds_retries_on_deliver_sms_task(
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
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert notification.status_reason == STATUS_REASON_UNDELIVERABLE
    mocked_check_and_queue_callback_task.assert_called_once()


def test_should_permanent_error_and_not_retry_if_invalid_email(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.delivery.send_to_providers.send_email_to_provider', side_effect=InvalidEmailError('bad email'))
    mocked_check_and_queue_callback_task = mocker.patch('app.celery.common.check_and_queue_callback_task')

    template = sample_template(template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE
    notification = sample_notification(template=template)

    with pytest.raises(NotificationTechnicalFailureException):
        deliver_email(notification.id)

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert notification.status_reason == STATUS_REASON_UNREACHABLE
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
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert notification.status_reason == STATUS_REASON_UNDELIVERABLE
    mocked_check_and_queue_callback_task.assert_called_once()


@pytest.mark.parametrize(
    'exception, status_reason',
    (
        (InvalidProviderException, STATUS_REASON_UNDELIVERABLE),
        (NullValueForNonConditionalPlaceholderException, STATUS_REASON_UNDELIVERABLE),
        (AttributeError, STATUS_REASON_UNDELIVERABLE),
        (RuntimeError, STATUS_REASON_UNDELIVERABLE),
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
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
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
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert notification.status_reason == STATUS_REASON_UNDELIVERABLE
    assert callback_mocker.called_once


@pytest.mark.parametrize(
    'exception, status_reason',
    (
        (InvalidProviderException, STATUS_REASON_UNDELIVERABLE),
        (NullValueForNonConditionalPlaceholderException, STATUS_REASON_UNDELIVERABLE),
        (AttributeError, STATUS_REASON_UNDELIVERABLE),
        (RuntimeError, STATUS_REASON_UNDELIVERABLE),
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
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
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


@pytest.mark.parametrize('code', ['Throttling', 'ThrottlingException'])
def test_should_retry_on_throttle(mocker, code):
    client = AwsSesClient()
    client.init_app('asdf', mocker.Mock(), mocker.Mock())
    e = botocore.exceptions.ClientError(
        {'Error': {'Code': code, 'Message': 'Maximum sending rate exceeded'}}, 'op name'
    )
    with pytest.raises(AwsSesClientThrottlingSendRateException):
        client._check_error_code(e, '1234')


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

    retry.assert_called_once()


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
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert notification.status_reason == STATUS_REASON_UNDELIVERABLE
    mocked_check_and_queue_callback_task.assert_called_once()


@pytest.mark.parametrize(
    'exception_message, status_reason',
    (
        ('Message too long', STATUS_REASON_UNDELIVERABLE),
        ('Destination phone number opted out', STATUS_REASON_BLOCKED),
    ),
)
def test_deliver_sms_non_retryables(
    notify_db_session,
    mocker,
    sample_service,
    sample_sms_sender,
    sample_template,
    sample_notification,
    exception_message,
    status_reason,
):
    """
    An SMS notification sent to a non-retryable exception should be marked as permanent failure and have an
    appropriate status reason.
    """

    service = sample_service()
    sms_sender = sample_sms_sender(service_id=service.id, sms_sender='17045555555')
    template = sample_template(service=service)
    notification = sample_notification(
        template=template,
        status=NOTIFICATION_CREATED,
        sms_sender_id=sms_sender.id,
    )
    assert notification.notification_type == SMS_TYPE
    assert notification.status == NOTIFICATION_CREATED
    assert notification.sms_sender_id == sms_sender.id
    assert notification.status_reason is None

    mock_send_sms_to_provider = mocker.patch(
        'app.delivery.send_to_providers.send_sms_to_provider',
        side_effect=NonRetryableException(exception_message),
    )
    deliver_sms(notification.id, sms_sender_id=notification.sms_sender_id)
    mock_send_sms_to_provider.assert_called_once()

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert notification.status_reason == status_reason


def test_deliver_push_happy_path_icn(
    client,
    rmock,
):
    url = f'{client.application.config["VETEXT_URL"]}/mobile/push/send'

    rmock.register_uri(
        'POST',
        url,
        json={'message': 'success'},
        status_code=201,
    )

    formatted_payload = {
        'appSid': f'{MobileAppType.VA_FLAGSHIP_APP}_SID',
        'templateSid': '2222',
        'icn': '3333',
        'personalization': {'%MSG_ID': '4444'},
    }

    # Should run without exceptions
    deliver_push(formatted_payload)

    assert rmock.called
    assert rmock.request_history[0].method == 'POST'
    assert rmock.request_history[0].url == url
    assert rmock.request_history[0].json()


def test_deliver_push_happy_path_topic(
    client,
    rmock,
):
    url = f'{client.application.config["VETEXT_URL"]}/mobile/push/send'

    rmock.register_uri(
        'POST',
        url,
        json={'message': 'success'},
        status_code=201,
    )

    formatted_payload = {
        'appSid': f'{MobileAppType.VA_FLAGSHIP_APP}_SID',
        'templateSid': '2222',
        'topicSid': '3333',
        'personalization': {'%MSG_ID': '4444'},
    }

    # Should run without exceptions
    deliver_push(formatted_payload)

    assert rmock.called
    assert rmock.request_history[0].method == 'POST'
    assert rmock.request_history[0].url == url
    assert rmock.request_history[0].json()


@pytest.mark.parametrize(
    'test_exception, status_code',
    [
        (ConnectTimeout(), None),
        (HTTPError(response=Response()), 429),
        (HTTPError(response=Response()), 500),
        (HTTPError(response=Response()), 502),
        (HTTPError(response=Response()), 503),
        (HTTPError(response=Response()), 504),
    ],
)
def test_deliver_push_retryable_exception(
    client,
    rmock,
    test_exception,
    status_code,
):
    if status_code is not None:
        test_exception.response.status_code = status_code

    url = f'{client.application.config["VETEXT_URL"]}/mobile/push/send'

    rmock.register_uri(
        'POST',
        url,
        exc=test_exception,
    )
    formatted_payload = {
        'appSid': f'{MobileAppType.VA_FLAGSHIP_APP}_SID',
        'templateSid': '2222',
        'icn': '3333',
        'personalization': {'%MSG_ID': '4444'},
    }

    with pytest.raises(AutoRetryException):
        deliver_push(formatted_payload)

    assert rmock.called
    assert rmock.request_history[0].method == 'POST'
    assert rmock.request_history[0].url == url
    assert rmock.request_history[0].json()


@pytest.mark.parametrize(
    'test_exception, status_code',
    [
        (HTTPError(response=Response()), 400),
        (HTTPError(response=Response()), 403),
        (HTTPError(response=Response()), 405),
        (RequestException(), None),
    ],
)
def test_deliver_push_nonretryable_exception(
    client,
    test_exception,
    status_code,
    rmock,
):
    if status_code is not None:
        test_exception.response.status_code = status_code

    url = f'{client.application.config["VETEXT_URL"]}/mobile/push/send'

    rmock.register_uri(
        'POST',
        url,
        exc=test_exception,
    )

    formatted_payload = {
        'appSid': f'{MobileAppType.VA_FLAGSHIP_APP}_SID',
        'templateSid': '2222',
        'icn': '3333',
        'personalization': {'%MSG_ID': '4444'},
    }

    with pytest.raises(NonRetryableException):
        deliver_push(formatted_payload)

    assert rmock.called
    assert rmock.request_history[0].method == 'POST'
    assert rmock.request_history[0].url == url
    assert rmock.request_history[0].json()


@patch('app.celery.provider_tasks.current_app.logger.warning')
@patch('app.celery.provider_tasks.log_and_update_critical_failure')
def test_handle_delivery_failure_duplication_prevention(mock_log_critical, mock_logger, notify_api):
    # Ensure a Duplication prevention RuntimeError is handled appropriately
    notification_id = str(uuid4())
    try:
        raise RuntimeError('Duplication prevention - notification.status = sending')
    except Exception as e:
        with pytest.raises(NotificationTechnicalFailureException):
            _handle_delivery_failure(None, None, None, e, notification_id, None)
    # Assert an appropriate warning was logged and that the log_and_update function was not called
    mock_logger.assert_called_with('Attempted to send duplicate notification for: %s', notification_id)
    mock_log_critical.assert_not_called()
