import pytest

from app.celery.common import RETRIES_EXCEEDED
from app.celery.exceptions import AutoRetryException
from app.constants import NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_TECHNICAL_FAILURE
from app.exceptions import NotificationTechnicalFailureException
from app.celery.lookup_va_profile_id_task import lookup_va_profile_id
from app.va.identifier import IdentifierType, UnsupportedIdentifierException
from app.va.mpi import (
    IdentifierNotFound,
    MpiRetryableException,
    BeneficiaryDeceasedException,
    MultipleActiveVaProfileIdsException,
    IncorrectNumberOfIdentifiersException,
    MpiNonRetryableException,
    NoSuchIdentifierException,
)


def test_should_call_mpi_client_and_save_va_profile_id(notify_api, mocker, sample_notification):
    notification = sample_notification()
    vaprofile_id = '1234'

    mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id', return_value=notification
    )

    mocked_dao_update_notification = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.dao_update_notification'
    )
    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(return_value=vaprofile_id)
    mocker.patch('app.celery.lookup_va_profile_id_task.mpi_client', new=mocked_mpi_client)

    lookup_va_profile_id(notification.id)

    mocked_mpi_client.get_va_profile_id.assert_called_with(notification)
    mocked_dao_update_notification.assert_called_once()
    # Call args is an array of calls. Each call has tuples for args.
    saved_notification = mocked_dao_update_notification.call_args[0][0]

    assert saved_notification.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value].id_value == vaprofile_id


@pytest.mark.parametrize(
    'exception, reason, failure',
    [
        (
            UnsupportedIdentifierException('some error'),
            UnsupportedIdentifierException.failure_reason,
            NOTIFICATION_PERMANENT_FAILURE,
        ),
        (
            IncorrectNumberOfIdentifiersException('some error'),
            IncorrectNumberOfIdentifiersException.failure_reason,
            NOTIFICATION_PERMANENT_FAILURE,
        ),
    ],
)
def test_should_not_retry_on_other_exception_and_should_update_to_appropriate_failure(
    client, mocker, sample_notification, exception, reason, failure
):
    notification = sample_notification()
    mocked_get_notification_by_id = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id', return_value=notification
    )

    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(side_effect=exception)
    mocker.patch('app.celery.lookup_va_profile_id_task.mpi_client', new=mocked_mpi_client)

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.update_notification_status_by_id'
    )

    mocked_lookup_contact_info = mocker.patch('app.celery.contact_information_tasks.lookup_contact_info.apply_async')

    mocked_retry = mocker.patch('app.celery.lookup_va_profile_id_task.lookup_va_profile_id.retry')

    lookup_va_profile_id(notification.id)

    mocked_get_notification_by_id.assert_called()
    mocked_lookup_contact_info.assert_not_called()

    mocked_update_notification_status_by_id.assert_called_with(notification.id, failure, status_reason=reason)
    mocked_retry.assert_not_called()


def test_should_retry_on_retryable_exception(client, mocker, sample_notification):
    notification = sample_notification()
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id', return_value=notification
    )

    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(side_effect=MpiRetryableException('some error'))
    mocker.patch('app.celery.lookup_va_profile_id_task.mpi_client', new=mocked_mpi_client)

    with pytest.raises(AutoRetryException):
        lookup_va_profile_id(notification.id)

    mocked_mpi_client.get_va_profile_id.assert_called_with(notification)


def test_should_update_notification_to_technical_failure_on_max_retries_and_should_call_callback(
    client, mocker, sample_notification
):
    """
    Raising MpiRetryableException and subsequently determining the the maximum number of retries has been
    reached should result in a technical failure.
    """

    notification = sample_notification()
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id', return_value=notification
    )

    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.lookup_va_profile_id_task.check_and_queue_callback_task',
    )

    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(side_effect=MpiRetryableException('some error'))
    mocker.patch('app.celery.lookup_va_profile_id_task.mpi_client', new=mocked_mpi_client)
    mocker.patch('app.celery.lookup_va_profile_id_task.can_retry', return_value=False)
    mocked_handle_max_retries_exceeded = mocker.patch(
        'app.celery.lookup_va_profile_id_task.handle_max_retries_exceeded'
    )

    with pytest.raises(NotificationTechnicalFailureException):
        lookup_va_profile_id(notification.id)

    mocked_handle_max_retries_exceeded.assert_called_once()
    mocked_check_and_queue_callback_task.assert_called_once_with(notification)


@pytest.mark.parametrize(
    'exception, reason',
    [
        (BeneficiaryDeceasedException('some error'), BeneficiaryDeceasedException.failure_reason),
        (IdentifierNotFound('some error'), IdentifierNotFound.failure_reason),
        (MultipleActiveVaProfileIdsException('some error'), MultipleActiveVaProfileIdsException.failure_reason),
        (UnsupportedIdentifierException('some error'), UnsupportedIdentifierException.failure_reason),
        (IncorrectNumberOfIdentifiersException('some error'), IncorrectNumberOfIdentifiersException.failure_reason),
        (NoSuchIdentifierException('some error'), NoSuchIdentifierException.failure_reason),
    ],
)
def test_should_permanently_fail_when_permanent_failure_exception(
    client, mocker, sample_notification, exception, reason
):
    notification = sample_notification()
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id', return_value=notification
    )

    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(side_effect=exception)
    mocker.patch('app.celery.lookup_va_profile_id_task.mpi_client', new=mocked_mpi_client)

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.update_notification_status_by_id'
    )

    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.lookup_va_profile_id_task.check_and_queue_callback_task',
    )

    lookup_va_profile_id(notification.id)

    mocked_update_notification_status_by_id.assert_called_with(
        notification.id, NOTIFICATION_PERMANENT_FAILURE, status_reason=reason
    )

    mocked_check_and_queue_callback_task.assert_called_with(notification)


@pytest.mark.parametrize(
    'exception, notification_status, failure_reason',
    [
        (
            MpiRetryableException,
            NOTIFICATION_TECHNICAL_FAILURE,
            RETRIES_EXCEEDED,
        ),
        (
            MpiNonRetryableException,
            NOTIFICATION_TECHNICAL_FAILURE,
            MpiNonRetryableException.failure_reason,
        ),
        (
            IncorrectNumberOfIdentifiersException,
            NOTIFICATION_PERMANENT_FAILURE,
            IncorrectNumberOfIdentifiersException.failure_reason,
        ),
        (
            IdentifierNotFound,
            NOTIFICATION_PERMANENT_FAILURE,
            IdentifierNotFound.failure_reason,
        ),
        (
            MultipleActiveVaProfileIdsException,
            NOTIFICATION_PERMANENT_FAILURE,
            MultipleActiveVaProfileIdsException.failure_reason,
        ),
        (
            BeneficiaryDeceasedException,
            NOTIFICATION_PERMANENT_FAILURE,
            BeneficiaryDeceasedException.failure_reason,
        ),
    ],
)
def test_caught_exceptions_should_set_status_reason_on_notification(
    client, mocker, sample_notification, exception, notification_status, failure_reason
):
    notification = sample_notification()
    mocker.patch('app.celery.lookup_va_profile_id_task.mpi_client.get_va_profile_id', side_effect=exception)
    if exception is MpiRetryableException:
        # Ensuring this does not retry and should raise a NotificationTechnicalFailureException
        mocker.patch('app.celery.lookup_va_profile_id_task.can_retry', return_value=False)
        mocker_handle_max_retries_exceeded = mocker.patch(
            'app.celery.lookup_va_profile_id_task.handle_max_retries_exceeded'
        )
        with pytest.raises(NotificationTechnicalFailureException):
            lookup_va_profile_id(notification.id)
        mocker_handle_max_retries_exceeded.assert_called_once()
    else:
        dao_path = 'app.celery.lookup_va_profile_id_task.notifications_dao.update_notification_status_by_id'
        mocker_mocker_update_notification_status_by_id = mocker.patch(dao_path)
        # Means it fell into the catch-all and we should see a technical exception
        if exception is MpiNonRetryableException:
            with pytest.raises(NotificationTechnicalFailureException):
                lookup_va_profile_id(notification.id)
        else:
            lookup_va_profile_id(notification.id)
        mocker_mocker_update_notification_status_by_id.assert_called_with(
            notification.id, notification_status, status_reason=failure_reason
        )


@pytest.mark.parametrize(
    'exception, reason',
    [
        (BeneficiaryDeceasedException('some error'), BeneficiaryDeceasedException.failure_reason),
        (IdentifierNotFound('some error'), IdentifierNotFound.failure_reason),
        (MultipleActiveVaProfileIdsException('some error'), MultipleActiveVaProfileIdsException.failure_reason),
        (UnsupportedIdentifierException('some error'), UnsupportedIdentifierException.failure_reason),
        (IncorrectNumberOfIdentifiersException('some error'), IncorrectNumberOfIdentifiersException.failure_reason),
        (NoSuchIdentifierException('some error'), NoSuchIdentifierException.failure_reason),
    ],
)
def test_should_call_callback_on_permanent_failure_exception(client, mocker, sample_notification, exception, reason):
    notification = sample_notification()
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id', return_value=notification
    )

    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.lookup_va_profile_id_task.check_and_queue_callback_task',
    )

    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(side_effect=exception)
    mocker.patch('app.celery.lookup_va_profile_id_task.mpi_client', new=mocked_mpi_client)

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.update_notification_status_by_id'
    )

    lookup_va_profile_id(notification.id)

    mocked_update_notification_status_by_id.assert_called_with(
        notification.id, NOTIFICATION_PERMANENT_FAILURE, status_reason=reason
    )

    mocked_check_and_queue_callback_task.assert_called_once_with(notification)


def test_should_not_call_callback_on_retryable_exception(client, mocker, sample_notification):
    notification = sample_notification()
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id', return_value=notification
    )

    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.lookup_va_profile_id_task.check_and_queue_callback_task',
    )

    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(side_effect=MpiRetryableException('some error'))
    mocker.patch('app.celery.lookup_va_profile_id_task.mpi_client', new=mocked_mpi_client)
    with pytest.raises(AutoRetryException):
        lookup_va_profile_id(notification.id)

    mocked_mpi_client.get_va_profile_id.assert_called_with(notification)
    mocked_check_and_queue_callback_task.assert_not_called()


def test_should_permanently_fail_when_technical_failure_exception(client, mocker, sample_notification):
    notification = sample_notification()
    mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id', return_value=notification
    )

    mocked_mpi_client = mocker.Mock()
    mocked_mpi_client.get_va_profile_id = mocker.Mock(side_effect=Exception)
    mocker.patch('app.celery.lookup_va_profile_id_task.mpi_client', new=mocked_mpi_client)

    mocked_update_notification_status_by_id = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.update_notification_status_by_id'
    )

    mocked_check_and_queue_callback_task = mocker.patch(
        'app.celery.lookup_va_profile_id_task.check_and_queue_callback_task',
    )

    with pytest.raises(NotificationTechnicalFailureException):
        lookup_va_profile_id(notification.id)

    mocked_update_notification_status_by_id.assert_called_with(
        notification.id, NOTIFICATION_TECHNICAL_FAILURE, status_reason='Unknown error from MPI'
    )

    mocked_check_and_queue_callback_task.assert_called_with(notification)
