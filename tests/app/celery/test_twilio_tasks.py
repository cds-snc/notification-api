from datetime import datetime, timedelta, timezone

from unittest.mock import patch

import pytest

from app.celery.exceptions import NonRetryableException
from app.celery.twilio_tasks import _get_notifications, update_twilio_status
from app.constants import (
    NOTIFICATION_CREATED,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
)


@pytest.mark.parametrize(
    'status, expected',
    [
        (NOTIFICATION_CREATED, True),
        (NOTIFICATION_SENDING, True),
        (NOTIFICATION_SENT, False),
        (NOTIFICATION_DELIVERED, False),
        (NOTIFICATION_TEMPORARY_FAILURE, False),
        (NOTIFICATION_PERMANENT_FAILURE, False),
    ],
)
def test_get_notifications_statuses(sample_notification, status, expected):
    """Test that _get_notifications() returns either a list with the test notification, or an empty list, depending
    on the parametrized status. If the status is in the NOTIFICATION_STATUS_TYPES_COMPLETED list, the notification is
    not returned."""
    created_at = datetime.now(timezone.utc) - timedelta(minutes=90)
    notification = sample_notification(created_at=created_at, status=status, sent_by='twilio')

    notifications = _get_notifications()
    notification_ids = [n.id for n in notifications]
    if expected:
        assert notification.id in notification_ids
    else:
        assert notification.id not in notification_ids


@pytest.mark.parametrize(
    'minute_offset, expected',
    [
        (5, False),
        (45, False),
        (90, True),
        (180, True),
    ],
)
def test_get_notifications_datefilter(sample_notification, minute_offset, expected):
    """Test that _get_notifications() returns either a list with the test notification, or an empty list, depending
    on the parametrized minute_offset. If the notification was created less than one hour ago, it is not returned."""
    created_at = datetime.now(timezone.utc) - timedelta(minutes=minute_offset)
    notification = sample_notification(created_at=created_at, status=NOTIFICATION_CREATED, sent_by='twilio')

    notifications = _get_notifications()
    notification_ids = [n.id for n in notifications]
    if expected:
        assert notification.id in notification_ids
    else:
        assert notification.id not in notification_ids


def test_update_twilio_status_with_results(mocker, sample_notification):
    """Test that update_twilio_status() calls twilio_sms_client.update_notification_status_override() with the
    notification reference when there are notifications to update."""
    notification = sample_notification(status=NOTIFICATION_CREATED, sent_by='twilio')

    mocker.patch('app.celery.twilio_tasks._get_notifications', return_value=[notification])

    with patch(
        'app.celery.twilio_tasks.twilio_sms_client.update_notification_status_override'
    ) as mock_update_notification_status_override:
        update_twilio_status()

    mock_update_notification_status_override.assert_called_once_with(notification.reference)


def test_update_twilio_status_no_results(mocker):
    """Test that update_twilio_status() does not call twilio_sms_client.update_notification_status_override() when
    there are no notifications to update."""
    mocker.patch('app.celery.twilio_tasks._get_notifications', return_value=[])

    with patch(
        'app.celery.twilio_tasks.twilio_sms_client.update_notification_status_override'
    ) as mock_update_notification_status_override:
        update_twilio_status()

    mock_update_notification_status_override.assert_not_called()


def test_update_twilio_status_exception(mocker, sample_notification):
    """Test that update_twilio_status() logs an error when twilio_sms_client.update_notification_status_override()
    raises a NonRetryableException, and does not update any more notifications."""
    created_at = datetime.now(timezone.utc) - timedelta(minutes=99)
    notification_one = sample_notification(status=NOTIFICATION_CREATED, sent_by='twilio', created_at=created_at)
    created_at = datetime.now(timezone.utc) - timedelta(minutes=90)
    sample_notification(status=NOTIFICATION_CREATED, sent_by='twilio', created_at=created_at)
    mock_twilio_status_override = mocker.patch(
        'app.celery.twilio_tasks.twilio_sms_client.update_notification_status_override',
        side_effect=[NonRetryableException('Test exception')],
    )
    mock_logger = mocker.patch('app.celery.twilio_tasks.current_app.logger.error')
    update_twilio_status()
    mock_logger.assert_called_once_with(
        'Failed to update notification %s: %s due to rate limit, aborting.', str(notification_one.id), 'Test exception'
    )
    mock_twilio_status_override.assert_called_once_with(notification_one.reference)
