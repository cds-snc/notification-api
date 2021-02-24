import pytest
from flask import json
from app.dao.notifications_dao import get_notification_by_id
from tests.app.db import create_notification


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_process_sendgrid_response(client, sample_email_template):
    notification = create_notification(template=sample_email_template, reference='ref')

    data = json.dumps([{
        "sg_message_id": "ref.abcd",
        "event": "delivered"
    }])

    client.post(
        path='/notifications/email/sendgrid',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )

    assert get_notification_by_id(notification.id).status == 'sent'


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_process_sendgrid_response_returs_a_400(client, sample_email_template):
    create_notification(template=sample_email_template, reference='ref')

    data = json.dumps([{
        "event": "delivered"
    }])

    response = client.post(
        path='/notifications/email/sendgrid',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )

    assert response.status == '400 BAD REQUEST'
