import uuid
from app.models import Notification, VA_PROFILE_ID
from app.celery.lookup_va_profile_id_task import lookup_va_profile_id


def test_should_call_mpi_client_and_save_va_profile_id(notify_api, mocker):
    notification_id = str(uuid.uuid4())
    vaprofile_id = '1234'
    notification = Notification(id=notification_id)

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

    lookup_va_profile_id(notification_id)

    mocked_mpi_client.get_va_profile_id.assert_called_with(notification)
    mocked_dao_update_notification.assert_called_once()
    # Call args is an array of calls. Each call has tuples for args.
    saved_notification = mocked_dao_update_notification.call_args[0][0]

    assert saved_notification.recipient_identifiers[VA_PROFILE_ID].id_value == vaprofile_id

