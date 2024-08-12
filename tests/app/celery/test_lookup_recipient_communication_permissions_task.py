import pytest
from collections import namedtuple
import uuid

from app.celery.lookup_recipient_communication_permissions_task import (
    lookup_recipient_communication_permissions,
    recipient_has_given_permission,
)
from app.exceptions import NotificationTechnicalFailureException, NotificationPermanentFailureException
from app.models import (
    CommunicationItem,
    EMAIL_TYPE,
    Notification,
    NOTIFICATION_PREFERENCES_DECLINED,
    RecipientIdentifier,
    SMS_TYPE,
)
from app.va.va_profile import VAProfileRetryableException
from app.va.va_profile.exceptions import CommunicationItemNotFoundException
from app.va.va_profile.va_profile_client import VAProfileClient
from app.va.identifier import IdentifierType


@pytest.fixture
def mock_communication_item(mocker):
    mock_communication_item = mocker.Mock()
    mock_communication_item.va_profile_item_id = 5
    mock_communication_item.default_send_indicator = True
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.get_communication_item',
        return_value=mock_communication_item,
    )


def mock_notification_with_vaprofile_id(mocker, notification_type=SMS_TYPE) -> Notification:
    id = uuid.uuid4()
    Notification = namedtuple('Notification', ['id', 'notification_type', 'template', 'recipient_identifiers'])
    MockTemplate = namedtuple('MockTemplate', ['communication_item_id'])
    template = MockTemplate(communication_item_id=1)
    return Notification(
        id=id,
        notification_type=notification_type,
        template=template,
        recipient_identifiers={
            f'{IdentifierType.VA_PROFILE_ID.value}': RecipientIdentifier(
                notification_id=id, id_type=IdentifierType.VA_PROFILE_ID.value, id_value='va-profile-id'
            ),
        },
    )


def mock_notification_without_vaprofile_id(mocker, notification_type=SMS_TYPE) -> Notification:
    id = uuid.uuid4()
    Notification = namedtuple('Notification', ['id', 'notification_type', 'template', 'recipient_identifiers'])
    MockTemplate = namedtuple('MockTemplate', ['communication_item_id'])
    template = MockTemplate(communication_item_id=1)
    return Notification(
        id=id,
        notification_type=notification_type,
        template=template,
        recipient_identifiers={
            f'{IdentifierType.PID.value}': RecipientIdentifier(
                notification_id=id, id_type=IdentifierType.PID.value, id_value='pid-id'
            ),
        },
    )


def test_lookup_recipient_communication_permissions_should_not_update_notification_status_if_recipient_has_permissions(
    client, mocker
):
    """
    This is the happy path for which no exceptions are raised, the notification has not reached any final state, and
    the next Celery task in the chain should execute.
    """

    notification = mock_notification_with_vaprofile_id(mocker)

    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.recipient_has_given_permission', return_value=None
    )
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.get_notification_by_id', return_value=notification
    )

    update_notification = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.update_notification_status_by_id'
    )

    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.check_and_queue_callback_task',
    )

    lookup_recipient_communication_permissions(notification.id)

    update_notification.assert_not_called()
    mocked_check_and_queue_callback_task.assert_not_called()


def test_lookup_recipient_communication_permissions_updates_notification_status_if_recipient_does_not_have_permissions(
    client, mocker
):
    notification = mock_notification_with_vaprofile_id(mocker)

    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.recipient_has_given_permission',
        return_value='Contact preferences set to false',
    )
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.get_notification_by_id', return_value=notification
    )

    update_notification = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.update_notification_status_by_id'
    )

    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.check_and_queue_callback_task',
    )

    with pytest.raises(NotificationPermanentFailureException):
        lookup_recipient_communication_permissions(str(notification.id))

    update_notification.assert_called_with(
        str(notification.id), NOTIFICATION_PREFERENCES_DECLINED, status_reason='Contact preferences set to false'
    )
    mocked_check_and_queue_callback_task.assert_called_once()


def test_recipient_has_given_permission_should_return_status_message_if_user_denies_permissions(
    client, mocker, mock_communication_item
):
    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(return_value=False)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.va_profile_client', new=mocked_va_profile_client
    )

    mock_task = mocker.Mock()
    permission_message = recipient_has_given_permission(
        mock_task, 'VAPROFILEID', '1', 'some-notification-id', SMS_TYPE, 'some-communication-id'
    )
    assert permission_message == 'Contact preferences set to false'


def test_recipient_has_given_permission_should_return_none_if_user_grants_permissions(
    client, mocker, mock_communication_item
):
    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(return_value=True)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.va_profile_client', new=mocked_va_profile_client
    )

    mock_task = mocker.Mock()
    permission_message = recipient_has_given_permission(
        mock_task, 'VAPROFILEID', '1', 'some-notification-id', SMS_TYPE, 'some-communication-id'
    )
    assert permission_message is None


def test_recipient_has_given_permission_should_return_none_if_user_permissions_not_set_and_no_com_item(
    client, mocker, fake_uuid
):
    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(side_effect=CommunicationItemNotFoundException)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.va_profile_client', new=mocked_va_profile_client
    )

    mocker.patch('app.celery.lookup_recipient_communication_permissions_task.get_communication_item', return_value=None)

    mock_task = mocker.Mock()
    permission_message = recipient_has_given_permission(
        mock_task, 'VAPROFILEID', '1', 'some-notification-id', SMS_TYPE, fake_uuid
    )
    assert permission_message is None


@pytest.mark.parametrize(
    'send_indicator', (True, False), ids=('default_send_indicator is True', 'default_send_indicator is False')
)
def test_recipient_has_given_permission_with_default_send_indicator_and_no_preference_set(
    client, mocker, send_indicator: bool
):
    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(side_effect=CommunicationItemNotFoundException)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.va_profile_client', new=mocked_va_profile_client
    )

    test_communication_item = CommunicationItem(
        id=uuid.uuid4(), va_profile_item_id=1, name='name', default_send_indicator=send_indicator
    )

    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.get_communication_item',
        return_value=test_communication_item,
    )

    mock_task = mocker.Mock()
    permission_message = recipient_has_given_permission(
        mock_task, 'VAPROFILEID', '1', 'some-notification-id', SMS_TYPE, 'some-communication-id'
    )

    if send_indicator:
        assert permission_message is None
    else:
        assert permission_message == 'No recipient opt-in found for explicit preference'


@pytest.mark.parametrize(
    'send_indicator', (True, False), ids=('default_send_indicator is True', 'default_send_indicator is False')
)
def test_recipient_has_given_permission_max_retries_exceeded(client, mocker, fake_uuid, send_indicator: bool):
    test_communication_item = CommunicationItem(
        id=uuid.uuid4(), va_profile_item_id=1, name='name', default_send_indicator=send_indicator
    )

    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.get_communication_item',
        return_value=test_communication_item,
    )

    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(side_effect=VAProfileRetryableException)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.va_profile_client', new=mocked_va_profile_client
    )

    mocker.patch('app.celery.lookup_recipient_communication_permissions_task.can_retry', return_value=False)

    mocked_max_retries = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.handle_max_retries_exceeded'
    )

    mock_task = mocker.Mock()

    with pytest.raises(NotificationTechnicalFailureException):
        recipient_has_given_permission(mock_task, 'VAPROFILEID', '1', 'some-notification-id', SMS_TYPE, fake_uuid)

    mocked_max_retries.assert_called()


def test_lookup_recipient_communication_permissions_max_retries_exceeded(client, mocker):
    notification = mock_notification_with_vaprofile_id(mocker)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.get_notification_by_id', return_value=notification
    )

    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.recipient_has_given_permission',
        side_effect=NotificationTechnicalFailureException,
    )

    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.check_and_queue_callback_task',
    )

    with pytest.raises(NotificationTechnicalFailureException):
        lookup_recipient_communication_permissions(notification.id)

    mocked_check_and_queue_callback_task.assert_called_once()


@pytest.mark.parametrize('notification_type', (SMS_TYPE, EMAIL_TYPE))
def test_recipient_has_given_permission_is_called_with_va_profile_id(client, mocker, notification_type):
    notification = mock_notification_with_vaprofile_id(mocker, notification_type)

    mock = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.recipient_has_given_permission', return_value=None
    )
    mocker.patch('app.celery.lookup_recipient_communication_permissions_task.update_notification_status_by_id')

    non_va_profile_id_type = IdentifierType.PID.value
    non_va_profile_id_value = 'pid-id'

    notification.recipient_identifiers[f'{non_va_profile_id_type}'] = RecipientIdentifier(
        notification_id=notification.id, id_type=non_va_profile_id_type, id_value=non_va_profile_id_value
    )

    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.get_notification_by_id', return_value=notification
    )

    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.check_and_queue_callback_task',
    )

    lookup_recipient_communication_permissions(str(notification.id))

    id_value = notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value].id_value

    mock.assert_called_once_with(
        lookup_recipient_communication_permissions,
        IdentifierType.VA_PROFILE_ID.value,
        id_value,
        str(notification.id),
        notification_type,
        notification.template.communication_item_id,
    )
    mocked_check_and_queue_callback_task.assert_not_called()


def test_lookup_recipient_communication_permissions_raises_exception_with_non_va_profile_id(client, mocker):
    notification = mock_notification_without_vaprofile_id(mocker)

    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.get_notification_by_id', return_value=notification
    )

    with pytest.raises(Exception):
        lookup_recipient_communication_permissions(str(notification.id))
