from datetime import datetime

import pytest
from flask import json
from sqlalchemy.exc import SQLAlchemyError

from app.dao.notifications_dao import get_notification_by_id
from app.notifications.notifications_email_callback import process_sendgrid_response
from app.errors import InvalidRequest

from tests.app.conftest import sample_notification as create_sample_notification
from tests.app.db import (
    create_notification
)



def test_process_sendgrid_response(client,
                                      notify_db,
                                      notify_db_session,
                                      sample_email_template,
                                      mocker):
    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference='ref',
        status='created',
        sent_at=datetime.utcnow()
    )

    data = json.dumps([{
            "sg_message_id": "ref.abcd",
            "event": "delivered"
        }])

    response = client.post(
        path='/notifications/email/sendgrid',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )

    assert get_notification_by_id(notification.id).status == 'sent'


def test_process_sendgrid_response_returs_a_400(client,
                                      notify_db,
                                      notify_db_session,
                                      sample_email_template,
                                      mocker):
    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference='ref',
        status='created',
        sent_at=datetime.utcnow()
    )

    data = json.dumps([{
            "event": "delivered"
        }])

    response = client.post(
        path='/notifications/email/sendgrid',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )

    assert response.status == '400 BAD REQUEST'
