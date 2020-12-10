import uuid

import pytest

from app.celery.contact_information_tasks import lookup_contact_info
from app.exceptions import NotificationTechnicalFailureException
from app.models import Notification, RecipientIdentifier, Service, NOTIFICATION_TECHNICAL_FAILURE
from app.va import IdentifierType
from app.va.va_profile import VAProfileClient, VAProfileNonRetryableException, \
    VAProfileRetryableException

EXAMPLE_VA_PROFILE_ID = '135'


@pytest.fixture(scope='function')
def notification():
    notification_id = str(uuid.uuid4())

    recipient_identifier = RecipientIdentifier(
        notification_id=notification_id,
        id_type=IdentifierType.VA_PROFILE_ID.value,
        id_value=EXAMPLE_VA_PROFILE_ID
    )

    notification = Notification(id=notification_id)
    notification.recipient_identifiers.set(recipient_identifier)

    return notification


def test_should_fetch_notification(client, mocker, notification):
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

    mocked_service = mocker.Mock(Service)
    mocked_service.research_mode = False
    notification.service = mocked_service

    lookup_contact_info(notification.id)

    mocked_get_notification_by_id.assert_called()
    mocked_va_profile_client.get_email.assert_called_with(EXAMPLE_VA_PROFILE_ID)
    mocked_update_notification.assert_called_with(notification)
    assert notification.to == 'test@test.org'


def test_should_not_retry_on_non_retryable_exception(client, mocker, notification):
    mocker.patch(
        'app.celery.contact_information_tasks.get_notification_by_id',
        return_value=notification
    )

    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_email = mocker.Mock(side_effect=VAProfileNonRetryableException('some error'))
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

    mocked_update_notification_status_by_id.assert_called_with(notification.id, NOTIFICATION_TECHNICAL_FAILURE)

    mocked_retry.assert_not_called()


def test_should_retry_on_retryable_exception(client, mocker, notification):
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

    mocked_update_notification_status_by_id.assert_called_with(notification.id, NOTIFICATION_TECHNICAL_FAILURE)
