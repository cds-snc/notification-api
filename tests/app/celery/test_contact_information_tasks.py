import uuid


from app.celery.contact_information_tasks import lookup_contact_info, lookup_va_profile_id
from app.clients.va_profile.va_profile_client import VAProfileClient
from app.models import Notification, VA_PROFILE_ID, RecipientIdentifier


def test_should_log_message_for_contact_information_tasks(client, mocker):
    mock_logger = mocker.patch('app.celery.contact_information_tasks.current_app.logger.info')
    notification_id = uuid.uuid4()

    lookup_contact_info(notification_id)
    mock_logger.assert_called_with('This task will look up contact information.')

    lookup_va_profile_id(notification_id)
    mock_logger.assert_called_with('This task will look up VA Profile ID.')


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
    mocker.patch(
        'app.celery.contact_information_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    lookup_contact_info(notification_id)

    mocked_get_notification_by_id.assert_called()
    mocked_va_profile_client.get_email.assert_called_with(example_va_profile_id)