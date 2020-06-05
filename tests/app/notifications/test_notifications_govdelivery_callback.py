from flask import json


def test_govdelivery_callback_gets_reference_from_payload(client, mocker):
    reference = "123456"
    data = json.dumps({
        "sid": "e6c48d6d2e4ad639ac4ef6cadd386ed7",
        "message_url": "https://tms.govdelivery.com/messages/sms/{0}".format(reference),
        "recipient_url": "https://tms.govdelivery.com/messages/sms/{0}/recipients/373810".format(reference),
        "status": "sent",
        "message_type": "sms",
        "completed_at": "2015-08-05 18:47:18 UTC"
    })

    mock_dao_get_notification_by_reference = mocker.patch(
        'app.notifications.notifications_govdelivery_callback.notifications_dao.dao_get_notification_by_reference'
    )

    client.post(
        path='/notifications/govdelivery',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )

    mock_dao_get_notification_by_reference.assert_called_with(reference)
