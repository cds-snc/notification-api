import pytest
from flask import json
from app.models import Notification


@pytest.fixture
def mock_dao_get_notification_by_reference(mocker):
    return mocker.patch(
        'app.notifications.notifications_govdelivery_callback.notifications_dao.dao_get_notification_by_reference'
    )


@pytest.fixture
def mock_map_govdelivery_status_to_notify_status(mocker):
    return mocker.patch(
        'app.notifications.notifications_govdelivery_callback.map_govdelivery_status_to_notify_status'
    )


@pytest.fixture
def mock_update_notification_status(mocker):
    return mocker.patch(
        'app.notifications.notifications_govdelivery_callback.notifications_dao._update_notification_status'
    )


def get_govdelivery_response(reference, status):
    return json.dumps({
        "sid": "some_sid",
        "message_url": "https://tms.govdelivery.com/messages/sms/{0}".format(reference),
        "recipient_url": "https://tms.govdelivery.com/messages/sms/{0}/recipients/373810".format(reference),
        "status": status,
        "message_type": "sms",
        "completed_at": "2015-08-05 18:47:18 UTC"
    })


def test_gets_reference_from_payload(
        client,
        mock_dao_get_notification_by_reference,
        mock_map_govdelivery_status_to_notify_status,
        mock_update_notification_status
):
    reference = "123456"
    data = get_govdelivery_response(reference, "sent")

    client.post(
        path='/notifications/govdelivery',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )

    mock_dao_get_notification_by_reference.assert_called_with(reference)


def test_maps_govdelivery_status_to_notify_status(
        client,
        mock_dao_get_notification_by_reference,
        mock_map_govdelivery_status_to_notify_status,
        mock_update_notification_status
):
    govdelivery_status = "sent"
    data = get_govdelivery_response("123456", govdelivery_status)

    client.post(
        path='/notifications/govdelivery',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )

    mock_map_govdelivery_status_to_notify_status.assert_called_with(govdelivery_status)


def test_should_update_notification_status(
        client,
        mocker,
        mock_dao_get_notification_by_reference,
        mock_map_govdelivery_status_to_notify_status,
        mock_update_notification_status
):
    notify_status = "sent"
    notification = mocker.Mock(Notification)

    data = get_govdelivery_response("123456", "sent")

    mock_dao_get_notification_by_reference.return_value = notification
    mock_map_govdelivery_status_to_notify_status.return_value = notify_status

    client.post(
        path='/notifications/govdelivery',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )

    mock_update_notification_status.assert_called_with(notification, notify_status)


def test_govdelivery_callback_returns_200(
        client,
        mock_dao_get_notification_by_reference,
        mock_map_govdelivery_status_to_notify_status,
        mock_update_notification_status
):
    data = get_govdelivery_response("123456", "sent")

    response = client.post(
        path='/notifications/govdelivery',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )

    assert response.status_code == 200
