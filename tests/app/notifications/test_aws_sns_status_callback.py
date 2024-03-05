from app import create_uuid
import pytest
from datetime import datetime
from freezegun import freeze_time
from app.models import NOTIFICATION_FAILED, NOTIFICATION_SENT, Notification
from app.notifications.aws_sns_status_callback import send_callback_metrics


@pytest.fixture
def mock_notification(mocker):
    notification = mocker.Mock(Notification)
    notification.id = create_uuid()
    notification.reference = create_uuid()
    notification.sent_at = datetime.utcnow()
    return notification


class TestSendcCllbackMetrics:
    @pytest.fixture
    def mocks_statsd(self, mocker):
        return mocker.patch('app.notifications.aws_sns_status_callback.statsd_client')

    @pytest.mark.parametrize('status', [NOTIFICATION_SENT, NOTIFICATION_FAILED])
    def test_should_increase_counter_for_status(self, client, mock_notification, mocks_statsd, status):
        mock_notification.status = status
        send_callback_metrics(mock_notification)
        mocks_statsd.incr.assert_called_with(f'callback.sns.{status}')

    @freeze_time('2020-11-03T22:45:00')
    @pytest.mark.parametrize('sent_at, should_call', [(None, False), (datetime(2020, 11, 3, 22, 30, 0), True)])
    def test_should_report_timing_only_when_notification_sent_at(
        self, client, mock_notification, mocks_statsd, sent_at, should_call
    ):
        mock_notification.sent_at = sent_at
        send_callback_metrics(mock_notification)
        if should_call:
            mocks_statsd.timing_with_dates.assert_called_with('callback.sns.elapsed-time', datetime.utcnow(), sent_at)
        else:
            mocks_statsd.timing_with_dates.assert_not_called
