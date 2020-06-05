import pytest
from flask import json


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


def test_gets_reference_from_payload(client, mock_dao_get_notification_by_reference):
    reference = "123456"
    data = json.dumps({
        "sid": "e6c48d6d2e4ad639ac4ef6cadd386ed7",
        "message_url": "https://tms.govdelivery.com/messages/sms/{0}".format(reference),
        "recipient_url": "https://tms.govdelivery.com/messages/sms/{0}/recipients/373810".format(reference),
        "status": "sent",
        "message_type": "sms",
        "completed_at": "2015-08-05 18:47:18 UTC"
    })

    client.post(
        path='/notifications/govdelivery',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )

    mock_dao_get_notification_by_reference.assert_called_with(reference)


def test_maps_govdelivery_status_to_notify_status(
        client,
        mock_dao_get_notification_by_reference,
        mock_map_govdelivery_status_to_notify_status
):
    govdelivery_status = "sent"
    data = json.dumps({
        "sid": "e6c48d6d2e4ad639ac4ef6cadd386ed7",
        "message_url": "https://tms.govdelivery.com/messages/sms/123456",
        "recipient_url": "https://tms.govdelivery.com/messages/sms/123456/recipients/373810",
        "status": govdelivery_status,
        "message_type": "sms",
        "completed_at": "2015-08-05 18:47:18 UTC"
    })

    client.post(
        path='/notifications/govdelivery',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )

    mock_map_govdelivery_status_to_notify_status.assert_called_with(govdelivery_status)
