import uuid

from app.celery.contact_information_tasks import lookup_contact_info
from app.clients.va_profile.va_profile_client import VAProfileClient
from app.models import Notification, VA_PROFILE_ID, RecipientIdentifier, Service


def test_should_fetch_notification(client, mocker):
    example_va_profile_id = '135'

    notification_id = str(uuid.uuid4())
    recipient_identifier = RecipientIdentifier(
        notification_id=notification_id,
        id_type=VA_PROFILE_ID,
        id_value=example_va_profile_id
    )
    notification = Notification(id=notification_id)
    notification.recipient_identifiers.set(recipient_identifier)

    mocked_get_notification_by_id = mocker.patch(
        'app.celery.contact_information_tasks.notifications_dao.get_notification_by_id',
        return_value=notification
    )

    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_email = mocker.Mock(return_value='test@test.org')
    mocker.patch(
        'app.celery.contact_information_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    mocked_update_notification = mocker.patch(
        'app.celery.contact_information_tasks.notifications_dao.dao_update_notification'
    )

    mock_send_notification_to_queue = mocker.patch('app.celery.contact_information_tasks.send_notification_to_queue')
    mocked_service = mocker.Mock(Service)
    mocked_service.research_mode = False
    notification.service = mocked_service

    lookup_contact_info(notification_id)

    mocked_get_notification_by_id.assert_called()
    mocked_va_profile_client.get_email.assert_called_with(example_va_profile_id)
    mocked_update_notification.assert_called_with(notification)
    assert notification.to == 'test@test.org'

    mock_send_notification_to_queue.assert_called_with(notification, False)
