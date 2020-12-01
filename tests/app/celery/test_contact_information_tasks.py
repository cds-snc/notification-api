import uuid
import pytest

from app.celery.contact_information_tasks import lookup_contact_info
from app.clients.va_profile.va_profile_client import VAProfileClient, VAProfileException
from app.config import QueueNames
from app.models import Notification, VA_PROFILE_ID, RecipientIdentifier, Service, NOTIFICATION_TECHNICAL_FAILURE


EXAMPLE_VA_PROFILE_ID = '135'


@pytest.fixture(scope='function')
def notification():
    notification_id = str(uuid.uuid4())

    recipient_identifier = RecipientIdentifier(
        notification_id=notification_id,
        id_type=VA_PROFILE_ID,
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

    mock_deliver_email = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    mocked_service = mocker.Mock(Service)
    mocked_service.research_mode = False
    notification.service = mocked_service

    lookup_contact_info(notification.id)

    mocked_get_notification_by_id.assert_called()
    mocked_va_profile_client.get_email.assert_called_with(EXAMPLE_VA_PROFILE_ID)
    mocked_update_notification.assert_called_with(notification)
    assert notification.to == 'test@test.org'

    mock_deliver_email.assert_called_with([notification.id], queue=QueueNames.SEND_EMAIL)


def test_should_update_notification_to_technical_failure_on_exception(client, mocker, notification):
    mocked_get_notification_by_id = mocker.patch(
        'app.celery.contact_information_tasks.get_notification_by_id',
        return_value=notification
    )

    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_email = mocker.Mock(side_effect=VAProfileException('some error'))
    mocker.patch(
        'app.celery.contact_information_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.contact_information_tasks.update_notification_status_by_id'
    )

    mock_deliver_email = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    lookup_contact_info(notification.id)

    mocked_get_notification_by_id.assert_called()
    mocked_va_profile_client.get_email.assert_called_with(EXAMPLE_VA_PROFILE_ID)
    mocked_update_notification_status_by_id.assert_called_with(notification.id, NOTIFICATION_TECHNICAL_FAILURE)

    mock_deliver_email.assert_not_called()
