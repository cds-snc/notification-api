import pytest

from app.celery.lookup_recipient_communication_permissions_task import (
    lookup_recipient_communication_permissions,
    recipient_has_given_permission
)
from app.models import NOTIFICATION_PREFERENCES_DECLINED, SMS_TYPE
from app.va.va_profile.va_profile_client import VAProfileClient


@pytest.fixture
def mock_communication_item(mocker):
    mock_communication_item = mocker.Mock()
    mock_communication_item.va_profile_item_id = 'some-va-profile-item-id'
    mocker.patch('app.celery.lookup_recipient_communication_permissions_task.get_communication_item',
                 return_value=mock_communication_item)


def test_lookup_recipient_communication_permissions_should_not_update_notification_status_if_recipient_has_permissions(
        client, mocker
):
    mocker.patch('app.celery.lookup_recipient_communication_permissions_task.recipient_has_given_permission',
                 return_value=True)
    mock_notification = mocker.Mock()
    mock_notification.id = 'some-id'
    update_notification = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.update_notification_status_by_id'
    )

    lookup_recipient_communication_permissions(
        'VAPROFILEID', '1', mock_notification.id, SMS_TYPE, 'some-communication-item-id'
    )
    update_notification.assert_not_called()


def test_lookup_recipient_communication_permissions_should_not_send_if_recipient_has_not_given_permission(
        client, mocker
):
    mocker.patch('app.celery.lookup_recipient_communication_permissions_task.recipient_has_given_permission',
                 return_value=False)
    update_notification = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.update_notification_status_by_id'
    )

    mock_notification = mocker.Mock()
    mock_notification.id = 'some-id'

    lookup_recipient_communication_permissions(
        'VAPROFILEID', '1', mock_notification.id, SMS_TYPE, 'some-communication-item-id'
    )

    update_notification.assert_called_once_with('some-id', NOTIFICATION_PREFERENCES_DECLINED)


def test_recipient_has_given_permission_should_return_false_if_user_denies_permissions(
        client, mocker, mock_communication_item
):
    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(return_value=False)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.va_profile_client',
        new=mocked_va_profile_client
    )

    mock_task = mocker.Mock()
    assert not recipient_has_given_permission(
        mock_task, 'VAPROFILEID', '1', 'some-notification-id', SMS_TYPE, 'some-communication-id'
    )


def test_recipient_has_given_permission_should_return_true_if_user_grants_permissions(
        client, mocker, mock_communication_item
):
    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(return_value=True)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.va_profile_client',
        new=mocked_va_profile_client
    )

    mock_task = mocker.Mock()
    assert recipient_has_given_permission(
        mock_task, 'VAPROFILEID', '1', 'some-notification-id', SMS_TYPE, 'some-communication-id'
    )
