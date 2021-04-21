import uuid

import pytest

from app.celery.contact_information_tasks import lookup_contact_info
from app.exceptions import NotificationTechnicalFailureException
from app.models import Notification, RecipientIdentifier, NOTIFICATION_TECHNICAL_FAILURE, \
    NOTIFICATION_PERMANENT_FAILURE, LETTER_TYPE, EMAIL_TYPE, SMS_TYPE
from app.va.identifier import IdentifierType
from app.va.va_profile import VAProfileClient, VAProfileNonRetryableException, \
    VAProfileRetryableException, NoContactInfoException

EXAMPLE_VA_PROFILE_ID = '135'
notification_id = str(uuid.uuid4())


@pytest.fixture(scope='function')
def notification():
    recipient_identifier = RecipientIdentifier(
        notification_id=notification_id,
        id_type=IdentifierType.VA_PROFILE_ID.value,
        id_value=EXAMPLE_VA_PROFILE_ID
    )

    notification = Notification(id=notification_id)
    notification.recipient_identifiers.set(recipient_identifier)
    notification.notification_type = LETTER_TYPE

    return notification


def test_should_get_email_address_and_update_notification(client, mocker, notification):
    notification.notification_type = EMAIL_TYPE
    mocked_get_notification_by_id = mocker.patch(
        'app.celery.contact_information_tasks.get_notification_by_id',
        return_value=notification
    )

    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_email = mocker.Mock(return_value='test@test.org')
    mocker.patch(
        'app.celery.contact_information_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    mocked_update_notification = mocker.patch(
        'app.celery.contact_information_tasks.dao_update_notification'
    )

    lookup_contact_info(notification.id)

    mocked_get_notification_by_id.assert_called()
    mocked_va_profile_client.get_email.assert_called_with(EXAMPLE_VA_PROFILE_ID)
    mocked_update_notification.assert_called_with(notification)
    assert notification.to == 'test@test.org'


def test_should_get_phone_number_and_update_notification(client, mocker, notification):
    notification.notification_type = SMS_TYPE
    mocked_get_notification_by_id = mocker.patch(
        'app.celery.contact_information_tasks.get_notification_by_id',
        return_value=notification
    )

    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_telephone = mocker.Mock(return_value='+15555555555')
    mocker.patch(
        'app.celery.contact_information_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    mocked_update_notification = mocker.patch(
        'app.celery.contact_information_tasks.dao_update_notification'
    )

    lookup_contact_info(notification.id)

    mocked_get_notification_by_id.assert_called()
    mocked_va_profile_client.get_telephone.assert_called_with(EXAMPLE_VA_PROFILE_ID)
    mocked_update_notification.assert_called_with(notification)
    assert notification.to == '+15555555555'


def test_should_not_retry_on_non_retryable_exception(client, mocker, notification):
    notification.notification_type = EMAIL_TYPE
    mocker.patch(
        'app.celery.contact_information_tasks.get_notification_by_id',
        return_value=notification
    )

    mocked_va_profile_client = mocker.Mock(VAProfileClient)

    exception = VAProfileNonRetryableException
    mocked_va_profile_client.get_email = mocker.Mock(side_effect=exception)
    mocker.patch(
        'app.celery.contact_information_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.contact_information_tasks.update_notification_status_by_id'
    )

    mocked_retry = mocker.patch('app.celery.contact_information_tasks.lookup_contact_info.retry')

    with pytest.raises(NotificationTechnicalFailureException):
        lookup_contact_info(notification.id)

    mocked_va_profile_client.get_email.assert_called_with(EXAMPLE_VA_PROFILE_ID)

    mocked_update_notification_status_by_id.assert_called_with(
        notification.id, NOTIFICATION_TECHNICAL_FAILURE, status_reason=exception.failure_reason
    )

    mocked_retry.assert_not_called()


def test_should_retry_on_retryable_exception(client, mocker, notification):
    notification.notification_type = EMAIL_TYPE
    mocker.patch(
        'app.celery.contact_information_tasks.get_notification_by_id',
        return_value=notification
    )

    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_email = mocker.Mock(side_effect=VAProfileRetryableException('some error'))
    mocker.patch(
        'app.celery.contact_information_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    mocked_retry = mocker.patch('app.celery.contact_information_tasks.lookup_contact_info.retry')

    lookup_contact_info(notification.id)

    mocked_va_profile_client.get_email.assert_called_with(EXAMPLE_VA_PROFILE_ID)

    mocked_retry.assert_called()


def test_should_update_notification_to_technical_failure_on_max_retries(client, mocker, notification):
    notification.notification_type = EMAIL_TYPE
    mocker.patch(
        'app.celery.contact_information_tasks.get_notification_by_id',
        return_value=notification
    )

    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    exception = VAProfileRetryableException(
        'RETRY FAILED: Max retries reached. '
        f'The task lookup_contact_info failed for notification {notification_id}. '
        'Notification has been updated to technical-failure'
    )
    mocked_va_profile_client.get_email = mocker.Mock(side_effect=exception)
    mocker.patch(
        'app.celery.contact_information_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.contact_information_tasks.update_notification_status_by_id'
    )

    mocker.patch(
        'app.celery.contact_information_tasks.lookup_contact_info.retry',
        side_effect=lookup_contact_info.MaxRetriesExceededError
    )

    with pytest.raises(NotificationTechnicalFailureException):
        lookup_contact_info(notification.id)

    mocked_va_profile_client.get_email.assert_called_with(EXAMPLE_VA_PROFILE_ID)

    mocked_update_notification_status_by_id.assert_called_with(
        notification.id, NOTIFICATION_TECHNICAL_FAILURE, status_reason=exception.failure_reason
    )


def test_should_update_notification_to_permanent_failure_on_no_contact_info_exception(client, mocker, notification):
    notification.notification_type = EMAIL_TYPE
    mocker.patch(
        'app.celery.contact_information_tasks.get_notification_by_id',
        return_value=notification
    )

    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    exception = NoContactInfoException
    mocked_va_profile_client.get_email = mocker.Mock(side_effect=exception)
    mocker.patch(
        'app.celery.contact_information_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.contact_information_tasks.update_notification_status_by_id'
    )

    mocked_request = mocker.Mock()
    mocked_chain = mocker.PropertyMock()
    mocked_chain.return_value = ['some-task-to-be-executed-next']
    type(mocked_request).chain = mocked_chain
    mocker.patch(
        'celery.app.task.Task.request',
        new=mocked_request
    )

    lookup_contact_info(notification.id)

    mocked_va_profile_client.get_email.assert_called_with(EXAMPLE_VA_PROFILE_ID)

    mocked_update_notification_status_by_id.assert_called_with(
        notification.id, NOTIFICATION_PERMANENT_FAILURE, status_reason=exception.failure_reason
    )

    mocked_chain.assert_called_with(None)


@pytest.mark.parametrize(
    'exception, throws_additional_exception, notification_status, exception_reason',
    [
        (
            VAProfileRetryableException,
            True,
            NOTIFICATION_TECHNICAL_FAILURE,
            VAProfileRetryableException.failure_reason
        ),
        (
            NoContactInfoException,
            False,
            NOTIFICATION_PERMANENT_FAILURE,
            NoContactInfoException.failure_reason
        ),
        (
            VAProfileNonRetryableException,
            True,
            NOTIFICATION_TECHNICAL_FAILURE,
            VAProfileNonRetryableException.failure_reason
        )
    ]
)
def test_exception_sets_failure_reason_if_thrown(
        client, mocker, notification, exception, throws_additional_exception, notification_status, exception_reason
):
    notification.notification_type = EMAIL_TYPE
    mocker.patch(
        'app.celery.contact_information_tasks.get_notification_by_id',
        return_value=notification
    )

    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_email = mocker.Mock(side_effect=exception)
    mocker.patch(
        'app.celery.contact_information_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.contact_information_tasks.update_notification_status_by_id'
    )

    mocker.patch(
        'app.celery.contact_information_tasks.lookup_contact_info.retry',
        side_effect=lookup_contact_info.MaxRetriesExceededError
    )

    if throws_additional_exception:
        with pytest.raises(NotificationTechnicalFailureException):
            lookup_contact_info(notification.id)
    else:
        lookup_contact_info(notification.id)

    mocked_update_notification_status_by_id.assert_called_once_with(
        notification.id, notification_status, status_reason=exception_reason
    )
