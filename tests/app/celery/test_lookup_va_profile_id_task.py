import uuid
from app.models import Notification
from app.celery.lookup_va_profile_id_task import lookup_va_profile_id


def test_should_load_notification_from_db(notify_api, mocker):
    notification_id = str(uuid.uuid4())
    notification = Notification(id=notification_id)
    mocked_get_notification_by_id = mocker.patch(
        'app.celery.lookup_va_profile_id_task.notifications_dao.get_notification_by_id',
        return_value=notification
    )

    lookup_va_profile_id(notification_id)
    mocked_get_notification_by_id.assert_called_with(notification_id)
