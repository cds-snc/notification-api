import uuid

import pytest

from app.celery.communication_item_tasks import process_communication_item_request, user_has_given_permission
from app.feature_flags import FeatureFlag
from app.models import NOTIFICATION_PREFERENCES_DECLINED
from app.va.va_profile.va_profile_client import CommunicationItemNotFoundException, VAProfileClient
from tests.app.oauth.test_rest import mock_toggle


@pytest.fixture
def check_user_communication_permissions_enabled(mocker):
    mock_toggle(mocker, FeatureFlag.CHECK_USER_COMMUNICATION_PERMISSIONS_ENABLED, 'True')


@pytest.fixture
def mock_template(mocker):
    mock_template = mocker.Mock()
    mock_template.communication_item_id = 'some-communication-item-id'
    mocker.patch('app.celery.communication_item_tasks.dao_get_template_by_id', return_value=mock_template)


@pytest.fixture
def mock_communication_item(mocker):
    mock_communication_item = mocker.Mock()
    mock_communication_item.va_profile_item_id = 'some-va-profile-item-id'
    mocker.patch('app.celery.communication_item_tasks.get_communication_item', return_value=mock_communication_item)


def test_process_communication_item_request_should_send_if_user_has_permissions(
        client, mocker, check_user_communication_permissions_enabled
):
    mocker.patch('app.celery.communication_item_tasks.user_has_given_permission',
                 return_value=True)
    send_to_queue = mocker.patch(
        'app.celery.communication_item_tasks.send_to_queue_for_recipient_info_based_on_recipient_identifier'
    )
    mock_notification = mocker.Mock()

    process_communication_item_request('VAPROFILEID', '1', uuid.uuid4(), mock_notification)

    send_to_queue.assert_called_once()


def test_process_communication_item_request_should_not_send_if_user_has_permissions(
        client, mocker, check_user_communication_permissions_enabled
):
    mocker.patch('app.celery.communication_item_tasks.user_has_given_permission',
                 return_value=False)
    update_notification = mocker.patch('app.celery.communication_item_tasks.update_notification_status_by_id')
    send_to_queue = mocker.patch(
        'app.celery.communication_item_tasks.send_to_queue_for_recipient_info_based_on_recipient_identifier'
    )
    mock_notification = mocker.Mock()
    mock_notification.id = 'some-id'

    process_communication_item_request('VAPROFILEID', '1', uuid.uuid4(), mock_notification)

    send_to_queue.assert_not_called()
    update_notification.assert_called_once_with('some-id', NOTIFICATION_PREFERENCES_DECLINED)


def test_user_has_given_permission_should_return_true_if_template_has_no_communication_item_id(
        client, mocker, check_user_communication_permissions_enabled
):
    # TODO: note that this test will be incorrect once we add default communication item preference logic
    mock_template = mocker.Mock()
    mock_template.communication_item_id = None
    mocker.patch('app.celery.communication_item_tasks.dao_get_template_by_id', return_value=mock_template)

    assert user_has_given_permission('VAPROFILEID', '1', str(uuid.uuid4()))


def test_user_has_given_permission_should_return_true_if_user_does_not_have_communication_item(
        client, mocker, check_user_communication_permissions_enabled, mock_template, mock_communication_item
):
    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(side_effect=CommunicationItemNotFoundException)
    mocker.patch(
        'app.celery.communication_item_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    assert user_has_given_permission('VAPROFILEID', '1', str(uuid.uuid4()))


def test_user_has_given_permission_should_return_false_if_user_denies_permissions(
        client, mocker, check_user_communication_permissions_enabled, mock_template, mock_communication_item
):
    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(return_value=False)
    mocker.patch(
        'app.celery.communication_item_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    assert not user_has_given_permission('VAPROFILEID', '1', str(uuid.uuid4()))


def test_user_has_given_permission_should_return_true_if_user_grants_permissions(
        client, mocker, check_user_communication_permissions_enabled, mock_template, mock_communication_item
):
    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(return_value=True)
    mocker.patch(
        'app.celery.communication_item_tasks.va_profile_client',
        new=mocked_va_profile_client
    )

    assert user_has_given_permission('VAPROFILEID', '1', str(uuid.uuid4()))
