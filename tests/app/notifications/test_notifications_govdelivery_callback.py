import pytest
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound

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


def get_govdelivery_request(reference, status):
    return {
        "sid": "some_sid",
        "message_url": "https://tms.govdelivery.com/messages/sms/{0}".format(reference),
        "recipient_url": "https://tms.govdelivery.com/messages/sms/{0}/recipients/373810".format(reference),
        "status": status,
        "message_type": "sms",
        "completed_at": "2015-08-05 18:47:18 UTC"
    }


def post(client, data):
    return client.post(
        path='/notifications/govdelivery',
        data=data,
        headers=[('Content-Type', 'application/x-www-form-urlencoded')]
    )


def test_gets_reference_from_payload(
        client,
        mock_dao_get_notification_by_reference,
        mock_map_govdelivery_status_to_notify_status,
        mock_update_notification_status
):
    reference = "123456"

    post(client, get_govdelivery_request(reference, "sent"))

    mock_dao_get_notification_by_reference.assert_called_with(reference)


def test_maps_govdelivery_status_to_notify_status(
        client,
        mock_dao_get_notification_by_reference,
        mock_map_govdelivery_status_to_notify_status,
        mock_update_notification_status
):
    govdelivery_status = "sent"

    post(client, get_govdelivery_request("123456", govdelivery_status))

    mock_map_govdelivery_status_to_notify_status.assert_called_with(govdelivery_status)


def test_should_update_notification_status(
        client,
        mocker,
        mock_dao_get_notification_by_reference,
        mock_map_govdelivery_status_to_notify_status,
        mock_update_notification_status
):
    notification = mocker.Mock(Notification)
    mock_dao_get_notification_by_reference.return_value = notification

    notify_status = "sent"
    mock_map_govdelivery_status_to_notify_status.return_value = notify_status

    post(client, get_govdelivery_request("123456", "sent"))

    mock_update_notification_status.assert_called_with(notification, notify_status)


def test_govdelivery_callback_returns_200(
        client,
        mock_dao_get_notification_by_reference,
        mock_map_govdelivery_status_to_notify_status,
        mock_update_notification_status,
):
    response = post(client, get_govdelivery_request("123456", "sent"))

    assert response.status_code == 200


@pytest.mark.parametrize("exception", [MultipleResultsFound(), NoResultFound()])
def test_govdelivery_callback_always_returns_200_after_expected_exceptions(
        client,
        mock_dao_get_notification_by_reference,
        mock_map_govdelivery_status_to_notify_status,
        mock_update_notification_status,
        exception
):
    mock_dao_get_notification_by_reference.side_effect = exception

    response = post(client, get_govdelivery_request("123456", "sent"))

    assert response.status_code == 200


def test_govdelivery_callback_raises_invalid_request_if_missing_data(client):
    response = post(client, {"not-the-right-key": "foo"})

    assert response.status_code == 400


def test_govdelivery_callback_raises_invalid_request_if_unrecognised_status(
        client,
        mock_map_govdelivery_status_to_notify_status
):
    mock_map_govdelivery_status_to_notify_status.side_effect = KeyError()

    response = post(client, get_govdelivery_request("123456", "some-status"))

    assert response.status_code == 400


def test_govdelivery_callback_raises_exceptions_after_unexpected_exceptions(
        client,
        mock_dao_get_notification_by_reference,
        mock_map_govdelivery_status_to_notify_status,
        mock_update_notification_status
):
    mock_dao_get_notification_by_reference.side_effect = Exception("Bad stuff happened")

    with pytest.raises(Exception):
        response = post(client, get_govdelivery_request("123456", "sent"))
        assert response.status_code == 500
