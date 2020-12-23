import uuid

import pytest

from app.exceptions import NotificationTechnicalFailureException
from app.models import Notification, NOTIFICATION_TECHNICAL_FAILURE, NOTIFICATION_PERMANENT_FAILURE
from app.celery.lookup_va_profile_id_task import lookup_va_profile_id
from app.va.identifier import IdentifierType
from app.va.mpi import UnsupportedIdentifierException, IdentifierNotFound, MpiRetryableException, \
    BeneficiaryDeceasedException, MultipleActiveVaProfileIdsException, IncorrectNumberOfIdentifiersException


@pytest.fixture(scope='function')
def notification():
    notification_id = str(uuid.uuid4())
    notification = Notification(id=notification_id)

    return notification


def test_should_call_mpi_client_and_save_va_profile_id(notify_api, mocker, notification):
    vaprofile_id = '1234'

    mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id',
        return_value=notification
    )

    mocked_dao_update_notification = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.dao_update_notification'
    )
    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(return_value=vaprofile_id)
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.mpi_client',
        new=mocked_mpi_client
    )

    lookup_va_profile_id(notification.id)

    mocked_mpi_client.get_va_profile_id.assert_called_with(notification)
    mocked_dao_update_notification.assert_called_once()
    # Call args is an array of calls. Each call has tuples for args.
    saved_notification = mocked_dao_update_notification.call_args[0][0]

    assert saved_notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value].id_value == vaprofile_id


@pytest.mark.parametrize(
    "exception",
    [UnsupportedIdentifierException('some error'), IncorrectNumberOfIdentifiersException('some error')]
)
def test_should_not_retry_on_nontryable_exception_and_should_update_to_technical_failure(
        client,
        mocker,
        notification,
        exception
):
    mocked_get_notification_by_id = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id',
        return_value=notification
    )

    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(side_effect=exception)
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.mpi_client',
        new=mocked_mpi_client
    )

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.update_notification_status_by_id'
    )

    mocked_lookup_contact_info = mocker.patch(
        'app.celery.contact_information_tasks.lookup_contact_info.apply_async'
    )

    mocked_retry = mocker.patch('app.celery.lookup_va_profile_id_task.lookup_va_profile_id.retry')

    with pytest.raises(NotificationTechnicalFailureException):
        lookup_va_profile_id(notification.id)

    mocked_get_notification_by_id.assert_called()
    mocked_lookup_contact_info.assert_not_called()

    mocked_update_notification_status_by_id.assert_called_with(notification.id, NOTIFICATION_TECHNICAL_FAILURE)
    mocked_retry.assert_not_called()


def test_should_retry_on_retryable_exception(client, mocker, notification):
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id',
        return_value=notification
    )

    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(side_effect=MpiRetryableException('some error'))
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.mpi_client',
        new=mocked_mpi_client
    )

    mocked_retry = mocker.patch('app.celery.lookup_va_profile_id_task.lookup_va_profile_id.retry')

    lookup_va_profile_id(notification.id)

    mocked_mpi_client.get_va_profile_id.assert_called_with(notification)
    mocked_retry.assert_called()


def test_should_update_notification_to_technical_failure_on_max_retries(client, mocker, notification):
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id',
        return_value=notification
    )

    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(side_effect=MpiRetryableException('some error'))
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.mpi_client',
        new=mocked_mpi_client
    )

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.update_notification_status_by_id'
    )

    mocker.patch(
        'app.celery.lookup_va_profile_id_task.lookup_va_profile_id.retry',
        side_effect=lookup_va_profile_id.MaxRetriesExceededError
    )

    with pytest.raises(NotificationTechnicalFailureException):
        lookup_va_profile_id(notification.id)

    mocked_update_notification_status_by_id.assert_called_with(notification.id, NOTIFICATION_TECHNICAL_FAILURE)


@pytest.mark.parametrize(
    "exception",
    [BeneficiaryDeceasedException('some error'),
     IdentifierNotFound('some error'),
     MultipleActiveVaProfileIdsException('some error')]
)
def test_should_permanently_fail_and_clear_chain_when_permanent_failure_exception(
        client,
        mocker,
        notification,
        exception
):
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id',
        return_value=notification
    )

    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(side_effect=exception)
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.mpi_client',
        new=mocked_mpi_client
    )

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.update_notification_status_by_id'
    )

    mocked_request = mocker.Mock()
    mocked_chain = mocker.PropertyMock()
    mocked_chain.return_value = ['some-task-to-be-executed-next']
    type(mocked_request).chain = mocked_chain
    mocker.patch(
        'celery.app.task.Task.request',
        new=mocked_request
    )

    lookup_va_profile_id(notification.id)

    mocked_update_notification_status_by_id.assert_called_with(notification.id, NOTIFICATION_PERMANENT_FAILURE)

    mocked_chain.assert_called_with(None)
