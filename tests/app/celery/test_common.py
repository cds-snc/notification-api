import datetime
from uuid import uuid4

from freezegun import freeze_time
import pytest

from app.celery.common import log_notification_total_time
from app.constants import (
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
)


@pytest.mark.parametrize('provider', ['pinpoint', 'ses', 'twilio'])
def test_ut_log_notification_total_time(
    notify_api,
    provider,
    mocker,
):
    mock_logger = mocker.patch('app.celery.common.current_app.logger.info')
    notification_id = uuid4()
    with freeze_time('2024-04-04 17:16:43'):
        created_at = datetime.datetime.fromisoformat('2024-04-04 17:16:41')

        log_notification_total_time(
            notification_id=notification_id,
            start_time=created_at,
            status=NOTIFICATION_DELIVERED,
            provider=provider,
        )

        mock_logger.assert_called_once_with(
            'notification %s took %ss total time to reach %s status - %s',
            notification_id,
            (datetime.datetime.now() - created_at).total_seconds(),
            NOTIFICATION_DELIVERED,
            provider,
        )


@pytest.mark.parametrize('provider', ['pinpoint', 'ses', 'twilio'])
@pytest.mark.parametrize(
    'status',
    [
        NOTIFICATION_CREATED,
        NOTIFICATION_PENDING,
        NOTIFICATION_SENDING,
        NOTIFICATION_SENT,
    ],
)
def test_ut_skip_log_notification_total_time(
    notify_api,
    status,
    provider,
    mocker,
):
    mock_logger = mocker.patch('app.celery.common.current_app.logger.info')
    log_notification_total_time(
        notification_id=uuid4(),
        start_time=datetime.datetime.now(),
        status=status,
        provider=provider,
    )

    mock_logger.assert_not_called()
