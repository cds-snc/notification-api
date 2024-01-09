from app import create_uuid
import json
import pytest
from datetime import datetime
from freezegun import freeze_time
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from app.models import NOTIFICATION_FAILED, NOTIFICATION_SENT, Notification
from app.notifications.aws_sns_status_callback import SNS_STATUS_FAILURE, SNS_STATUS_SUCCESS, send_callback_metrics


@pytest.fixture
def mock_dao_get_notification_by_reference(mocker):
    return mocker.patch('app.notifications.aws_sns_status_callback.dao_get_notification_by_reference')


@pytest.fixture
def mock_update_notification_status(mocker):
    return mocker.patch('app.notifications.aws_sns_status_callback._update_notification_status')


@pytest.fixture
def mock_process_service_callback(mocker):
    return mocker.patch('app.notifications.aws_sns_status_callback.process_service_callback')


@pytest.fixture
def mock_send_callback_metrics(mocker):
    return mocker.patch('app.notifications.aws_sns_status_callback.send_callback_metrics')


@pytest.fixture
def mock_notification(mocker):
    notification = mocker.Mock(Notification)
    notification.id = create_uuid()
    notification.reference = create_uuid()
    notification.sent_at = datetime.utcnow()
    return notification


# https://docs.aws.amazon.com/sns/latest/dg/sms_stats_cloudwatch.html
def get_sns_delivery_status_payload(reference, status):
    return {
        'notification': {'messageId': reference, 'timestamp': '2016-06-28 00:40:34.558'},
        'delivery': {
            'phoneCarrier': 'My Phone Carrier',
            'mnc': 270,
            'destination': '+1XXX5550100',
            'priceInUSD': 0.00645,
            'smsType': 'Transactional',
            'mcc': 310,
            'providerResponse': 'Message has been accepted by phone carrier',
            'dwellTimeMs': 599,
            'dwellTimeMsUntilDeviceAck': 1344,
        },
        'status': status,
    }


def payload_with_missing_message_id():
    payload = get_sns_delivery_status_payload('some-reference', SNS_STATUS_SUCCESS)
    del payload['notification']['messageId']
    return payload


def payload_with_missing_status():
    payload = get_sns_delivery_status_payload('some-reference', SNS_STATUS_SUCCESS)
    del payload['status']
    return payload


def post(client, data):
    return client.post(
        path='/notifications/sms/sns', data=json.dumps(data), headers=[('Content-Type', 'application/json')]
    )


class TestProcessSNSDeliveryStatus:
    @pytest.mark.skip(reason='Endpoint disabled and slated for removal')
    @pytest.mark.parametrize(
        'data',
        [
            payload_with_missing_message_id(),
            payload_with_missing_status(),
            get_sns_delivery_status_payload(create_uuid(), 'NOT_A_VALID_STATE'),
            get_sns_delivery_status_payload('not-uuid', SNS_STATUS_SUCCESS),
        ],
    )
    def test_returns_bad_request_on_schema_validation_errors(self, client, data):
        response = post(client, data)
        assert response.status_code == 400

    @pytest.mark.skip(reason='Endpoint disabled and slated for removal')
    def test_loads_notification_by_reference(
        self,
        client,
        mock_notification,
        mock_dao_get_notification_by_reference,
        mock_update_notification_status,
        mock_process_service_callback,
    ):
        mock_dao_get_notification_by_reference.return_value = mock_notification
        post(client, get_sns_delivery_status_payload(mock_notification.reference, SNS_STATUS_SUCCESS))

        mock_dao_get_notification_by_reference.assert_called_with(mock_notification.reference)

    @pytest.mark.skip(reason='Endpoint disabled and slated for removal')
    @pytest.mark.parametrize('exception', [MultipleResultsFound(), NoResultFound()])
    def test_returns_404_when_unable_to_load_notification(
        self, client, mock_notification, mock_dao_get_notification_by_reference, exception
    ):
        mock_dao_get_notification_by_reference.side_effect = exception
        response = post(client, get_sns_delivery_status_payload(mock_notification.reference, SNS_STATUS_SUCCESS))

        assert response.status_code == 404

    @pytest.mark.skip(reason='Endpoint disabled and slated for removal')
    @pytest.mark.parametrize(
        'sns_status, status', [(SNS_STATUS_SUCCESS, NOTIFICATION_SENT), (SNS_STATUS_FAILURE, NOTIFICATION_FAILED)]
    )
    def test_should_update_notification_status(
        self,
        client,
        mock_notification,
        mock_dao_get_notification_by_reference,
        mock_update_notification_status,
        mock_process_service_callback,
        sns_status,
        status,
    ):
        mock_dao_get_notification_by_reference.return_value = mock_notification
        post(client, get_sns_delivery_status_payload(mock_notification.reference, sns_status))

        mock_update_notification_status.assert_called_with(mock_notification, status)

    @pytest.mark.skip(reason='Endpoint disabled and slated for removal')
    def test_should_process_service_callback(
        self,
        client,
        mock_notification,
        mock_dao_get_notification_by_reference,
        mock_update_notification_status,
        mock_process_service_callback,
    ):
        mock_dao_get_notification_by_reference.return_value = mock_notification
        mock_update_notification_status.return_value = mock_notification
        post(client, get_sns_delivery_status_payload(mock_notification.reference, SNS_STATUS_SUCCESS))

        mock_process_service_callback.assert_called_with(mock_notification)

    @pytest.mark.skip(reason='Endpoint disabled and slated for removal')
    def test_should_send_callback_metrics(
        self,
        client,
        mock_notification,
        mock_dao_get_notification_by_reference,
        mock_update_notification_status,
        mock_process_service_callback,
        mock_send_callback_metrics,
    ):
        mock_dao_get_notification_by_reference.return_value = mock_notification
        mock_update_notification_status.return_value = mock_notification
        post(client, get_sns_delivery_status_payload(mock_notification.reference, SNS_STATUS_SUCCESS))

        mock_send_callback_metrics.assert_called_with(mock_notification)

    @pytest.mark.skip(reason='Endpoint disabled and slated for removal')
    def test_returns_204(
        self,
        client,
        mock_notification,
        mock_dao_get_notification_by_reference,
        mock_update_notification_status,
        mock_process_service_callback,
    ):
        mock_dao_get_notification_by_reference.return_value = mock_notification
        mock_update_notification_status.return_value = mock_notification
        response = post(client, get_sns_delivery_status_payload(mock_notification.reference, SNS_STATUS_SUCCESS))

        assert response.status_code == 204


class TestSendcCllbackMetrics:
    @pytest.fixture
    def mocks_statsd(self, mocker):
        return mocker.patch('app.notifications.aws_sns_status_callback.statsd_client')

    @pytest.mark.parametrize('status', [NOTIFICATION_SENT, NOTIFICATION_FAILED])
    def test_should_increase_counter_for_status(self, mock_notification, mocks_statsd, status):
        mock_notification.status = status
        send_callback_metrics(mock_notification)
        mocks_statsd.incr.assert_called_with(f'callback.sns.{status}')

    @freeze_time('2020-11-03T22:45:00')
    @pytest.mark.parametrize('sent_at, should_call', [(None, False), (datetime(2020, 11, 3, 22, 30, 0), True)])
    def test_should_report_timing_only_when_notification_sent_at(
        self, mock_notification, mocks_statsd, sent_at, should_call
    ):
        mock_notification.sent_at = sent_at
        send_callback_metrics(mock_notification)
        if should_call:
            mocks_statsd.timing_with_dates.assert_called_with('callback.sns.elapsed-time', datetime.utcnow(), sent_at)
        else:
            mocks_statsd.timing_with_dates.assert_not_called
