import uuid

import pytest
from datetime import datetime
from dateutil import parser

from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound

from app.models import NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE, Notification, Complaint
from app.clients.email.govdelivery_client import govdelivery_status_map
from app.notifications.notifications_govdelivery_callback import create_complaint


@pytest.fixture
def mock_dao_get_notification_by_reference(mocker):
    return mocker.patch(
        'app.notifications.notifications_govdelivery_callback.notifications_dao.dao_get_notification_by_reference'
    )


@pytest.fixture
def mock_update_notification_status(mocker):
    return mocker.patch(
        'app.notifications.notifications_govdelivery_callback.notifications_dao._update_notification_status'
    )


@pytest.fixture
def mock_statsd(mocker):
    return mocker.patch('app.notifications.notifications_govdelivery_callback.statsd_client')


def get_govdelivery_request(reference, status, error_message=None):
    return {
        'sid': 'some_sid',
        'message_url': 'https://tms.govdelivery.com/messages/sms/{0}'.format(reference),
        'recipient_url': 'https://tms.govdelivery.com/messages/sms/{0}/recipients/373810'.format(reference),
        'status': status,
        'message_type': 'sms',
        'completed_at': '2015-08-05 18:47:18 UTC',
        'error_message': error_message,
    }


def post(client, data):
    return client.post(
        path='/notifications/govdelivery', data=data, headers=[('Content-Type', 'application/x-www-form-urlencoded')]
    )


def test_gets_reference_from_payload(client, mock_dao_get_notification_by_reference, mock_update_notification_status):
    reference = '123456'

    post(client, get_govdelivery_request(reference, 'sent'))

    mock_dao_get_notification_by_reference.assert_called_with(reference)


@pytest.mark.parametrize(
    'govdelivery_status, notify_status', [('sent', NOTIFICATION_DELIVERED), ('failed', NOTIFICATION_PERMANENT_FAILURE)]
)
def test_should_update_notification_status(
    client,
    mocker,
    mock_dao_get_notification_by_reference,
    mock_update_notification_status,
    govdelivery_status,
    notify_status,
):
    notification = mocker.Mock(Notification)
    notification.sent_at = datetime.utcnow()
    mock_dao_get_notification_by_reference.return_value = notification

    post(client, get_govdelivery_request('123456', govdelivery_status))

    mock_update_notification_status.assert_called_with(notification, notify_status)


def test_should_call_publish_complaint_when_govdelivery_status_is_blacklisted(
    client, mocker, mock_dao_get_notification_by_reference, mock_update_notification_status
):
    notification = mocker.Mock(Notification)
    notification.sent_at = datetime.utcnow()
    test_email = 'some@email'
    notification.to = test_email
    mock_dao_get_notification_by_reference.return_value = notification

    mock_publish_complaint = mocker.patch('app.notifications.notifications_govdelivery_callback.publish_complaint')
    mock_complaint = mocker.Mock(Complaint)

    mocker.patch('app.notifications.notifications_govdelivery_callback.create_complaint', return_value=mock_complaint)

    mocker.patch('app.notifications.notifications_govdelivery_callback.save_complaint')

    post(client, get_govdelivery_request('123456', 'blacklisted'))

    mock_update_notification_status.assert_called_with(notification, NOTIFICATION_PERMANENT_FAILURE)
    mock_publish_complaint.assert_called_once_with(mock_complaint, notification, test_email)


def test_govdelivery_callback_returns_200(
    client,
    mock_dao_get_notification_by_reference,
    mock_update_notification_status,
):
    response = post(client, get_govdelivery_request('123456', 'sent'))

    assert response.status_code == 200


@pytest.mark.parametrize(
    'exception, exception_name', [(MultipleResultsFound(), 'MultipleResultsFound'), (NoResultFound(), 'NoResultFound')]
)
def test_govdelivery_callback_always_returns_200_after_expected_exceptions(
    client, mock_dao_get_notification_by_reference, mock_statsd, exception, exception_name
):
    mock_dao_get_notification_by_reference.side_effect = exception

    response = post(client, get_govdelivery_request('123456', 'sent'))
    mock_statsd.incr.assert_called_with(f'callback.govdelivery.failure.{exception_name}')

    assert response.status_code == 200


def test_govdelivery_callback_raises_invalid_request_if_missing_data(client):
    response = post(client, {'not-the-right-key': 'foo'})

    assert response.status_code == 400


def test_govdelivery_callback_raises_invalid_request_if_unrecognised_status(client):
    response = post(client, get_govdelivery_request('123456', 'some-status'))

    assert response.status_code == 400


def test_govdelivery_callback_raises_exceptions_after_unexpected_exceptions(
    client,
    mock_dao_get_notification_by_reference,
):
    mock_dao_get_notification_by_reference.side_effect = Exception('Bad stuff happened')

    with pytest.raises(Exception):
        response = post(client, get_govdelivery_request('123456', 'sent'))
        assert response.status_code == 500


@pytest.mark.parametrize('govdelivery_status', ['sent', 'failed', 'canceled'])
def test_should_store_statistics_when_successful(
    client,
    mocker,
    mock_dao_get_notification_by_reference,
    mock_update_notification_status,
    mock_statsd,
    govdelivery_status,
):
    notification = mocker.Mock(Notification)
    notification.sent_at = datetime.utcnow()
    mock_dao_get_notification_by_reference.return_value = notification

    post(client, get_govdelivery_request('123456', govdelivery_status))

    mock_statsd.incr.assert_called_with(f'callback.govdelivery.{govdelivery_status_map[govdelivery_status]}')
    mock_statsd.timing_with_dates.assert_called_with(
        'callback.govdelivery.elapsed-time', mocker.ANY, notification.sent_at
    )


def test_should_log_failure_reason(
    client, mocker, mock_dao_get_notification_by_reference, mock_update_notification_status, mock_statsd
):
    notification = mocker.Mock(Notification)
    mock_dao_get_notification_by_reference.return_value = notification
    logger = mocker.spy(client.application.logger, 'info')
    error_message = 'Some failure message'

    post(client, get_govdelivery_request('123456', 'failed', error_message))

    logs = [args[0] for args, kwargs in logger.call_args_list]
    assert any(error_message in log for log in logs)


def test_create_complaint_should_return_complaint_with_correct_info(mocker, notify_api):
    request = get_govdelivery_request('1111', 'blacklisted')

    test_email = 'some_email@gov.gov'

    mocker.patch('app.notifications.notifications_govdelivery_callback.save_complaint')

    test_notification = Notification(id=uuid.uuid4(), to=test_email, service_id=uuid.uuid4())

    expected_complaint = Complaint(
        notification_id=test_notification.id,
        service_id=test_notification.service_id,
        feedback_id=request['sid'],
        complaint_type=request['message_type'],
        complaint_date=parser.parse(request['completed_at']),
    )

    with notify_api.app_context():
        complaint = create_complaint(request, test_notification)

        assert_complaints_are_equal(expected_complaint, complaint)


def assert_complaints_are_equal(expected_complaint, actual_complaint):
    assert expected_complaint.notification_id == actual_complaint.notification_id
    assert expected_complaint.service_id == actual_complaint.service_id
    assert expected_complaint.feedback_id == actual_complaint.feedback_id
    assert expected_complaint.complaint_type == actual_complaint.complaint_type
    assert expected_complaint.complaint_date == actual_complaint.complaint_date
