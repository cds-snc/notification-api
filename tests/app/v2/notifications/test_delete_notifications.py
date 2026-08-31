import pytest
from flask import json

from app.models import Notification, ScheduledNotification
from tests import create_authorization_header
from tests.app.db import (
    create_notification,
    create_service,
    create_template,
    save_notification,
    save_scheduled_notification,
)


def test_delete_scheduled_notification_returns_200(client, sample_template):
    notification = save_scheduled_notification(
        create_notification(template=sample_template),
        scheduled_for="2099-05-12 15:15",
    )

    auth_header = create_authorization_header(service_id=notification.service_id)
    response = client.delete(
        path="/v2/notifications/{}".format(notification.id),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 200
    assert response.headers["Content-type"] == "application/json"
    assert json.loads(response.get_data(as_text=True)) == {"result": "success"}

    assert Notification.query.get(notification.id) is None
    assert ScheduledNotification.query.filter_by(notification_id=notification.id).first() is None


def test_delete_notification_that_is_not_scheduled_returns_400(client, sample_template):
    notification = save_notification(create_notification(template=sample_template))

    auth_header = create_authorization_header(service_id=notification.service_id)
    response = client.delete(
        path="/v2/notifications/{}".format(notification.id),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    json_response = json.loads(response.get_data(as_text=True))
    assert json_response["errors"] == [
        {"error": "BadRequestError", "message": "Notification is not scheduled and cannot be deleted"}
    ]

    assert Notification.query.get(notification.id) is not None


def test_delete_scheduled_notification_that_has_already_been_sent_returns_400(client, sample_template):
    # a status other than "created" causes the scheduled notification to be marked as not pending
    notification = save_scheduled_notification(
        create_notification(template=sample_template, status="sending"),
        scheduled_for="2017-05-12 15:15",
    )

    auth_header = create_authorization_header(service_id=notification.service_id)
    response = client.delete(
        path="/v2/notifications/{}".format(notification.id),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    json_response = json.loads(response.get_data(as_text=True))
    assert json_response["errors"] == [
        {"error": "BadRequestError", "message": "Notification has already been sent and cannot be deleted"}
    ]

    assert Notification.query.get(notification.id) is not None


def test_delete_notification_nonexistent_id_returns_404(client, sample_notification):
    auth_header = create_authorization_header(service_id=sample_notification.service_id)
    response = client.delete(
        path="/v2/notifications/dd4b8b9d-d414-4a83-9256-580046bf18f9",
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 404
    json_response = json.loads(response.get_data(as_text=True))
    assert json_response == {"message": "Notification not found in database", "result": "error"}


def test_delete_notification_belonging_to_another_service_returns_404(client, sample_template):
    notification = save_scheduled_notification(
        create_notification(template=sample_template),
        scheduled_for="2099-05-12 15:15",
    )

    other_service = create_service(service_name="another service", check_if_service_exists=True)
    create_template(service=other_service)

    auth_header = create_authorization_header(service_id=other_service.id)
    response = client.delete(
        path="/v2/notifications/{}".format(notification.id),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 404
    assert Notification.query.get(notification.id) is not None


@pytest.mark.parametrize("id", ["1234-badly-formatted-id-7890", "0"])
def test_delete_notification_invalid_id_returns_400(client, sample_notification, id):
    auth_header = create_authorization_header(service_id=sample_notification.service_id)
    response = client.delete(
        path="/v2/notifications/{}".format(id),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    json_response = json.loads(response.get_data(as_text=True))
    assert json_response["errors"] == [{"error": "ValidationError", "message": "notification_id is not a valid UUID"}]
