import base64
import csv
import uuid
from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import call

import pytest
from flask import current_app, json
from freezegun import freeze_time

from app.dao.jobs_dao import dao_get_job_by_id
from app.dao.service_sms_sender_dao import dao_update_service_sms_sender
from app.models import (
    EMAIL_TYPE,
    INTERNATIONAL_SMS_TYPE,
    NOTIFICATION_CREATED,
    SCHEDULE_NOTIFICATIONS,
    SMS_TYPE,
    UPLOAD_DOCUMENT,
    Notification,
    ScheduledNotification,
)
from app.schema_validation import validate
from app.utils import get_document_url
from app.v2.errors import RateLimitError
from app.v2.notifications.notification_schemas import (
    post_email_response,
    post_sms_response,
)
from tests import create_authorization_header
from tests.app.conftest import document_download_response, sample_template
from tests.app.db import (
    create_api_key,
    create_reply_to_email,
    create_service,
    create_service_sms_sender,
    create_service_with_inbound_number,
    create_template,
)
from tests.conftest import set_config


def rows_to_csv(rows):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    return output.getvalue()


@pytest.mark.parametrize("reference", [None, "reference_from_client"])
def test_post_sms_notification_returns_201(notify_api, client, sample_template_with_placeholders, mocker, reference):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    mocked = mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
    data = {
        "phone_number": "+16502532222",
        "template_id": str(sample_template_with_placeholders.id),
        "personalisation": {" Name": "Jo"},
    }
    if reference:
        data.update({"reference": reference})
    auth_header = create_authorization_header(service_id=sample_template_with_placeholders.service_id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_sms_response) == resp_json
    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].status == NOTIFICATION_CREATED
    notification_id = notifications[0].id
    assert notifications[0].postage is None
    assert resp_json["id"] == str(notification_id)
    assert resp_json["reference"] == reference
    assert resp_json["content"]["body"] == sample_template_with_placeholders.content.replace("(( Name))", "Jo")
    assert resp_json["content"]["from_number"] == current_app.config["FROM_NUMBER"]
    assert "v2/notifications/{}".format(notification_id) in resp_json["uri"]
    assert resp_json["template"]["id"] == str(sample_template_with_placeholders.id)
    assert resp_json["template"]["version"] == sample_template_with_placeholders.version
    assert (
        "services/{}/templates/{}".format(
            sample_template_with_placeholders.service_id,
            sample_template_with_placeholders.id,
        )
        in resp_json["template"]["uri"]
    )
    assert not resp_json["scheduled_for"]
    assert mocked.called


@pytest.mark.parametrize("reference", [None, "reference_from_client"])
def test_post_sms_notification_with_persistance_in_celery_returns_201(
    notify_api, client, sample_template_with_placeholders, mocker, reference
):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = 1
    mocked = mocker.patch("app.celery.tasks.save_sms.apply_async")
    data = {
        "phone_number": "+16502532222",
        "template_id": str(sample_template_with_placeholders.id),
        "personalisation": {" Name": "Jo"},
    }
    if reference:
        data.update({"reference": reference})
    auth_header = create_authorization_header(service_id=sample_template_with_placeholders.service_id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_sms_response) == resp_json
    assert resp_json["reference"] == reference
    assert resp_json["content"]["body"] == sample_template_with_placeholders.content.replace("(( Name))", "Jo")
    assert resp_json["content"]["from_number"] == current_app.config["FROM_NUMBER"]
    assert "v2/notifications/{}".format(resp_json["id"]) in resp_json["uri"]
    assert resp_json["template"]["id"] == str(sample_template_with_placeholders.id)
    assert resp_json["template"]["version"] == sample_template_with_placeholders.version
    assert (
        "services/{}/templates/{}".format(
            sample_template_with_placeholders.service_id,
            sample_template_with_placeholders.id,
        )
        in resp_json["template"]["uri"]
    )
    assert not resp_json["scheduled_for"]
    assert mocked.called


class TestRedisBatchSaving:
    @pytest.mark.parametrize("reference", [None, "reference_from_client"])
    def test_post_notification_with_redis_batch_saving_returns_201(
        self, notify_api, client, sample_template_with_placeholders, mocker, reference
    ):
        notify_api.config["FF_REDIS_BATCH_SAVING"] = True
        mocked_redis_publish = mocker.patch("app.v2.notifications.post_notifications.RedisQueue.publish")

        data = {
            "phone_number": "+16502532222",
            "template_id": str(sample_template_with_placeholders.id),
            "personalisation": {" Name": "Jo"},
        }
        if reference:
            data.update({"reference": reference})
        auth_header = create_authorization_header(service_id=sample_template_with_placeholders.service_id)

        response = client.post(
            path="/v2/notifications/sms",
            data=json.dumps(data),
            headers=[("Content-Type", "application/json"), auth_header],
        )
        assert response.status_code == 201
        resp_json = json.loads(response.get_data(as_text=True))
        assert validate(resp_json, post_sms_response) == resp_json
        assert resp_json["reference"] == reference
        assert resp_json["content"]["body"] == sample_template_with_placeholders.content.replace("(( Name))", "Jo")
        assert resp_json["content"]["from_number"] == current_app.config["FROM_NUMBER"]
        assert "v2/notifications/{}".format(resp_json["id"]) in resp_json["uri"]
        assert resp_json["template"]["id"] == str(sample_template_with_placeholders.id)
        assert resp_json["template"]["version"] == sample_template_with_placeholders.version
        assert (
            "services/{}/templates/{}".format(
                sample_template_with_placeholders.service_id,
                sample_template_with_placeholders.id,
            )
            in resp_json["template"]["uri"]
        )
        assert not resp_json["scheduled_for"]
        assert mocked_redis_publish.called


def test_post_sms_notification_uses_inbound_number_as_sender(notify_api, client, notify_db_session, mocker):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    notify_api.config["FF_REDIS_BATCH_SAVING"] = False
    service = create_service_with_inbound_number(inbound_number="1")
    template = create_template(service=service, content="Hello (( Name))\nYour thing is due soon")
    mocked = mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
    data = {
        "phone_number": "+16502532222",
        "template_id": str(template.id),
        "personalisation": {" Name": "Jo"},
    }
    auth_header = create_authorization_header(service_id=service.id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_sms_response) == resp_json
    notifications = Notification.query.all()
    assert len(notifications) == 1
    notification_id = notifications[0].id
    assert resp_json["id"] == str(notification_id)
    assert resp_json["content"]["from_number"] == "1"
    assert notifications[0].reply_to_text == "1"
    mocked.assert_called_once_with([str(notification_id)], queue="send-sms-tasks")


def test_post_sms_notification_uses_inbound_number_reply_to_as_sender(notify_api, client, notify_db_session, mocker):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    notify_api.config["FF_REDIS_BATCH_SAVING"] = False
    service = create_service_with_inbound_number(inbound_number="6502532222")
    template = create_template(service=service, content="Hello (( Name))\nYour thing is due soon")
    mocked = mocker.patch("app.celery.provider_tasks.deliver_throttled_sms.apply_async")
    data = {
        "phone_number": "+16502532222",
        "template_id": str(template.id),
        "personalisation": {" Name": "Jo"},
    }
    auth_header = create_authorization_header(service_id=service.id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_sms_response) == resp_json
    notifications = Notification.query.all()
    assert len(notifications) == 1
    notification_id = notifications[0].id
    assert resp_json["id"] == str(notification_id)
    assert resp_json["content"]["from_number"] == "+16502532222"
    assert notifications[0].reply_to_text == "+16502532222"
    mocked.assert_called_once_with([str(notification_id)], queue="send-throttled-sms-tasks")


def test_post_sms_notification_returns_201_with_sms_sender_id(notify_api, client, sample_template_with_placeholders, mocker):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    notify_api.config["FF_REDIS_BATCH_SAVING"] = False
    sms_sender = create_service_sms_sender(service=sample_template_with_placeholders.service, sms_sender="123456")
    mocked = mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
    data = {
        "phone_number": "+16502532222",
        "template_id": str(sample_template_with_placeholders.id),
        "personalisation": {" Name": "Jo"},
        "sms_sender_id": str(sms_sender.id),
    }
    auth_header = create_authorization_header(service_id=sample_template_with_placeholders.service_id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_sms_response) == resp_json
    assert resp_json["content"]["from_number"] == sms_sender.sms_sender
    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].reply_to_text == sms_sender.sms_sender
    mocked.assert_called_once_with([resp_json["id"]], queue="send-sms-tasks")


def test_post_sms_notification_with_celery_persistence_returns_201_with_sms_sender_id(
    notify_api, client, sample_template_with_placeholders, mocker
):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = 1
    notify_api.config["FF_REDIS_BATCH_SAVING"] = False
    sms_sender = create_service_sms_sender(service=sample_template_with_placeholders.service, sms_sender="123456")
    mocked = mocker.patch("app.celery.tasks.save_sms.apply_async")
    data = {
        "phone_number": "+16502532222",
        "template_id": str(sample_template_with_placeholders.id),
        "personalisation": {" Name": "Jo"},
        "sms_sender_id": str(sms_sender.id),
    }
    auth_header = create_authorization_header(service_id=sample_template_with_placeholders.service_id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_sms_response) == resp_json
    assert resp_json["content"]["from_number"] == sms_sender.sms_sender
    assert mocked.called


def test_post_sms_notification_uses_sms_sender_id_reply_to(notify_api, client, sample_template_with_placeholders, mocker):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    notify_api.config["FF_REDIS_BATCH_SAVING"] = False
    sms_sender = create_service_sms_sender(service=sample_template_with_placeholders.service, sms_sender="6502532222")
    mocked = mocker.patch("app.celery.provider_tasks.deliver_throttled_sms.apply_async")
    data = {
        "phone_number": "+16502532222",
        "template_id": str(sample_template_with_placeholders.id),
        "personalisation": {" Name": "Jo"},
        "sms_sender_id": str(sms_sender.id),
    }
    auth_header = create_authorization_header(service_id=sample_template_with_placeholders.service_id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_sms_response) == resp_json
    assert resp_json["content"]["from_number"] == "+16502532222"
    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].reply_to_text == "+16502532222"
    mocked.assert_called_once_with([resp_json["id"]], queue="send-throttled-sms-tasks")


def test_notification_reply_to_text_is_original_value_if_sender_is_changed_after_post_notification(
    notify_api, client, sample_template, mocker
):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    notify_api.config["FF_REDIS_BATCH_SAVING"] = False
    sms_sender = create_service_sms_sender(service=sample_template.service, sms_sender="123456", is_default=False)
    mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
    data = {
        "phone_number": "+16502532222",
        "template_id": str(sample_template.id),
        "sms_sender_id": str(sms_sender.id),
    }
    auth_header = create_authorization_header(service_id=sample_template.service_id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    dao_update_service_sms_sender(
        service_id=sample_template.service_id,
        service_sms_sender_id=sms_sender.id,
        is_default=sms_sender.is_default,
        sms_sender="updated",
    )

    assert response.status_code == 201
    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].reply_to_text == "123456"


@pytest.mark.parametrize(
    "notification_type, key_send_to, send_to",
    [
        ("sms", "phone_number", "+16502532222"),
        ("email", "email_address", "sample@email.com"),
    ],
)
def test_post_notification_returns_400_and_missing_template(client, sample_service, notification_type, key_send_to, send_to):

    data = {key_send_to: send_to, "template_id": str(uuid.uuid4())}
    auth_header = create_authorization_header(service_id=sample_service.id)

    response = client.post(
        path="/v2/notifications/{}".format(notification_type),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    assert response.headers["Content-type"] == "application/json"

    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["status_code"] == 400
    assert error_json["errors"] == [{"error": "BadRequestError", "message": "Template not found"}]


@pytest.mark.parametrize(
    "notification_type, key_send_to, send_to",
    [
        ("sms", "phone_number", "+16502532222"),
        ("email", "email_address", "sample@email.com"),
        (
            "letter",
            "personalisation",
            {"address_line_1": "The queen", "postcode": "SW1 1AA"},
        ),
    ],
)
def test_post_notification_returns_401_and_well_formed_auth_error(
    client, sample_template, notification_type, key_send_to, send_to
):
    data = {key_send_to: send_to, "template_id": str(sample_template.id)}

    response = client.post(
        path="/v2/notifications/{}".format(notification_type),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json")],
    )

    assert response.status_code == 401
    assert response.headers["Content-type"] == "application/json"
    error_resp = json.loads(response.get_data(as_text=True))
    assert error_resp["status_code"] == 401
    assert error_resp["errors"] == [
        {
            "error": "AuthError",
            "message": "Unauthorized, authentication token must be provided",
        }
    ]


@pytest.mark.parametrize(
    "notification_type, key_send_to, send_to",
    [
        ("sms", "phone_number", "+16502532222"),
        ("email", "email_address", "sample@email.com"),
    ],
)
def test_notification_returns_400_and_for_schema_problems(client, sample_template, notification_type, key_send_to, send_to):
    data = {key_send_to: send_to, "template": str(sample_template.id)}
    auth_header = create_authorization_header(service_id=sample_template.service_id)

    response = client.post(
        path="/v2/notifications/{}".format(notification_type),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    assert response.headers["Content-type"] == "application/json"
    error_resp = json.loads(response.get_data(as_text=True))
    assert error_resp["status_code"] == 400
    assert {
        "error": "ValidationError",
        "message": "template_id is a required property",
    } in error_resp["errors"]
    assert {
        "error": "ValidationError",
        "message": "Additional properties are not allowed (template was unexpected)",
    } in error_resp["errors"]


@pytest.mark.parametrize("reference", [None, "reference_from_client"])
def test_post_email_notification_returns_201(notify_api, client, sample_email_template_with_placeholders, mocker, reference):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    mocked = mocker.patch("app.celery.provider_tasks.deliver_email.apply_async")
    data = {
        "email_address": sample_email_template_with_placeholders.service.users[0].email_address,
        "template_id": sample_email_template_with_placeholders.id,
        "personalisation": {"name": "Bob"},
    }
    if reference:
        data.update({"reference": reference})
    auth_header = create_authorization_header(service_id=sample_email_template_with_placeholders.service_id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_email_response) == resp_json
    notification = Notification.query.one()
    assert notification.status == NOTIFICATION_CREATED
    assert notification.postage is None
    assert resp_json["id"] == str(notification.id)
    assert resp_json["reference"] == reference
    assert notification.reference is None
    assert notification.reply_to_text is None
    assert resp_json["content"]["body"] == sample_email_template_with_placeholders.content.replace("((name))", "Bob")
    assert resp_json["content"]["subject"] == sample_email_template_with_placeholders.subject.replace("((name))", "Bob")
    assert resp_json["content"]["from_email"] == "{}@{}".format(
        sample_email_template_with_placeholders.service.email_from,
        current_app.config["NOTIFY_EMAIL_DOMAIN"],
    )
    assert "v2/notifications/{}".format(notification.id) in resp_json["uri"]
    assert resp_json["template"]["id"] == str(sample_email_template_with_placeholders.id)
    assert resp_json["template"]["version"] == sample_email_template_with_placeholders.version
    assert (
        "services/{}/templates/{}".format(
            str(sample_email_template_with_placeholders.service_id),
            str(sample_email_template_with_placeholders.id),
        )
        in resp_json["template"]["uri"]
    )
    assert not resp_json["scheduled_for"]
    assert mocked.called


@pytest.mark.parametrize("reference", [None, "reference_from_client"])
def test_post_email_notification_returns_201_with_celery_persistence(
    notify_api, client, sample_email_template_with_placeholders, mocker, reference
):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = 1
    mocked = mocker.patch("app.celery.tasks.save_email.apply_async")
    data = {
        "email_address": sample_email_template_with_placeholders.service.users[0].email_address,
        "template_id": sample_email_template_with_placeholders.id,
        "personalisation": {"name": "Bob"},
    }
    if reference:
        data.update({"reference": reference})
    auth_header = create_authorization_header(service_id=sample_email_template_with_placeholders.service_id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_email_response) == resp_json
    assert resp_json["reference"] == reference
    assert resp_json["content"]["body"] == sample_email_template_with_placeholders.content.replace("((name))", "Bob")
    assert resp_json["content"]["subject"] == sample_email_template_with_placeholders.subject.replace("((name))", "Bob")
    assert resp_json["content"]["from_email"] == "{}@{}".format(
        sample_email_template_with_placeholders.service.email_from,
        current_app.config["NOTIFY_EMAIL_DOMAIN"],
    )
    assert "v2/notifications/{}".format(resp_json["id"]) in resp_json["uri"]
    assert resp_json["template"]["id"] == str(sample_email_template_with_placeholders.id)
    assert resp_json["template"]["version"] == sample_email_template_with_placeholders.version
    assert (
        "services/{}/templates/{}".format(
            str(sample_email_template_with_placeholders.service_id),
            str(sample_email_template_with_placeholders.id),
        )
        in resp_json["template"]["uri"]
    )
    assert not resp_json["scheduled_for"]
    assert mocked.called


@pytest.mark.parametrize(
    "recipient, notification_type",
    [
        ("simulate-delivered@notification.canada.ca", EMAIL_TYPE),
        ("simulate-delivered-2@notification.canada.ca", EMAIL_TYPE),
        ("simulate-delivered-3@notification.canada.ca", EMAIL_TYPE),
        ("6132532222", "sms"),
        ("6132532223", "sms"),
        ("6132532224", "sms"),
    ],
)
def test_should_not_persist_or_send_notification_if_simulated_recipient(
    client, recipient, notification_type, sample_email_template, sample_template, mocker
):
    apply_async = mocker.patch("app.celery.provider_tasks.deliver_{}.apply_async".format(notification_type))

    if notification_type == "sms":
        data = {"phone_number": recipient, "template_id": str(sample_template.id)}
    else:
        data = {"email_address": recipient, "template_id": str(sample_email_template.id)}

    auth_header = create_authorization_header(service_id=sample_email_template.service_id)

    response = client.post(
        path="/v2/notifications/{}".format(notification_type),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 201
    apply_async.assert_not_called()
    assert json.loads(response.get_data(as_text=True))["id"]
    assert Notification.query.count() == 0


@pytest.mark.parametrize(
    "notification_type, key_send_to, send_to",
    [
        ("sms", "phone_number", "6502532222"),
        ("email", "email_address", "sample@email.com"),
    ],
)
@pytest.mark.parametrize("process_type", ["priority", "bulk"])
def test_send_notification_uses_appropriate_queue_according_to_template_process_type(
    notify_api,
    client,
    sample_service,
    mocker,
    notification_type,
    key_send_to,
    send_to,
    process_type,
):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    mocker.patch("app.celery.provider_tasks.deliver_{}.apply_async".format(notification_type))

    sample = create_template(
        service=sample_service,
        template_type=notification_type,
        process_type=process_type,
    )
    mocked = mocker.patch("app.celery.provider_tasks.deliver_{}.apply_async".format(notification_type))

    data = {key_send_to: send_to, "template_id": str(sample.id)}

    auth_header = create_authorization_header(service_id=sample.service_id)

    response = client.post(
        path="/v2/notifications/{}".format(notification_type),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    notification_id = json.loads(response.data)["id"]

    assert response.status_code == 201
    mocked.assert_called_once_with([notification_id], queue=f"{process_type}-tasks")


@pytest.mark.parametrize(
    "notification_type, key_send_to, send_to",
    [
        ("sms", "phone_number", "6502532222"),
        ("email", "email_address", "sample@email.com"),
    ],
)
def test_returns_a_429_limit_exceeded_if_rate_limit_exceeded(
    notify_api, client, sample_service, mocker, notification_type, key_send_to, send_to
):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    sample = create_template(service=sample_service, template_type=notification_type)
    save_mock = mocker.patch("app.v2.notifications.post_notifications.db_save_and_send_notification")
    mocker.patch(
        "app.v2.notifications.post_notifications.check_rate_limiting",
        side_effect=RateLimitError("LIMIT", "INTERVAL", "TYPE"),
    )

    data = {key_send_to: send_to, "template_id": str(sample.id)}

    auth_header = create_authorization_header(service_id=sample.service_id)

    response = client.post(
        path="/v2/notifications/{}".format(notification_type),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    error = json.loads(response.data)["errors"][0]["error"]
    message = json.loads(response.data)["errors"][0]["message"]
    status_code = json.loads(response.data)["status_code"]
    assert response.status_code == 429
    assert error == "RateLimitError"
    assert message == "Exceeded rate limit for key type TYPE of LIMIT requests per INTERVAL seconds"
    assert status_code == 429

    assert not save_mock.called


def test_post_sms_notification_returns_400_if_not_allowed_to_send_int_sms(
    client,
    notify_db_session,
):
    service = create_service(service_permissions=[SMS_TYPE])
    template = create_template(service=service)

    data = {"phone_number": "+20-12-1234-1234", "template_id": template.id}
    auth_header = create_authorization_header(service_id=service.id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    assert response.headers["Content-type"] == "application/json"

    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["status_code"] == 400
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": "Cannot send to international mobile numbers",
        }
    ]


def test_post_sms_notification_with_archived_reply_to_id_returns_400(client, sample_template):
    archived_sender = create_service_sms_sender(sample_template.service, "12345", is_default=False, archived=True)
    data = {
        "phone_number": "+16502532222",
        "template_id": sample_template.id,
        "sms_sender_id": archived_sender.id,
    }
    auth_header = create_authorization_header(service_id=sample_template.service_id)
    response = client.post(
        path="v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert (
        "sms_sender_id {} does not exist in database for service id {}".format(archived_sender.id, sample_template.service_id)
        in resp_json["errors"][0]["message"]
    )
    assert "BadRequestError" in resp_json["errors"][0]["error"]


@pytest.mark.parametrize(
    "recipient,label,permission_type, notification_type,expected_error",
    [
        ("6502532222", "phone_number", "email", "sms", "text messages"),
        ("someone@test.com", "email_address", "sms", "email", "emails"),
    ],
)
def test_post_sms_notification_returns_400_if_not_allowed_to_send_notification(
    notify_db_session,
    client,
    recipient,
    label,
    permission_type,
    notification_type,
    expected_error,
):
    service = create_service(service_permissions=[permission_type])
    sample_template_without_permission = create_template(service=service, template_type=notification_type)
    data = {label: recipient, "template_id": sample_template_without_permission.id}
    auth_header = create_authorization_header(service_id=sample_template_without_permission.service.id)

    response = client.post(
        path="/v2/notifications/{}".format(sample_template_without_permission.template_type),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    assert response.headers["Content-type"] == "application/json"

    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["status_code"] == 400
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": "Service is not allowed to send {}".format(expected_error),
        }
    ]


@pytest.mark.parametrize("restricted", [True, False])
def test_post_sms_notification_returns_400_if_number_not_safelisted(notify_db_session, client, restricted):
    service = create_service(restricted=restricted, service_permissions=[SMS_TYPE, INTERNATIONAL_SMS_TYPE])
    template = create_template(service=service)
    create_api_key(service=service, key_type="team")

    data = {
        "phone_number": "+16132532235",
        "template_id": template.id,
    }
    auth_header = create_authorization_header(service_id=service.id, key_type="team")

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["status_code"] == 400
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": "Can’t send to this recipient using a team-only API key "
            f'- see {get_document_url("en", "keys.html#team-and-safelist")}',
        }
    ]


# TODO: duplicate
def test_post_sms_notification_returns_201_if_allowed_to_send_int_sms(
    notify_api,
    sample_service,
    sample_template,
    client,
    mocker,
):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")

    data = {"phone_number": "+20-12-1234-1234", "template_id": sample_template.id}
    auth_header = create_authorization_header(service_id=sample_service.id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 201
    assert response.headers["Content-type"] == "application/json"


# TODO: duplicate
def test_post_sms_notification_returns_201_if_allowed_to_send_int_sms_with_celery_persistence(
    notify_api,
    sample_service,
    sample_template,
    client,
    mocker,
):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = 1
    mocker.patch("app.celery.tasks.save_sms.apply_async")

    data = {"phone_number": "+20-12-1234-1234", "template_id": sample_template.id}
    auth_header = create_authorization_header(service_id=sample_service.id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 201
    assert response.headers["Content-type"] == "application/json"


def test_post_sms_should_persist_supplied_sms_number(notify_api, client, sample_template_with_placeholders, mocker):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    mocked = mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
    data = {
        "phone_number": "+16502532222",
        "template_id": str(sample_template_with_placeholders.id),
        "personalisation": {" Name": "Jo"},
    }

    auth_header = create_authorization_header(service_id=sample_template_with_placeholders.service_id)

    response = client.post(
        path="/v2/notifications/sms",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    notifications = Notification.query.all()
    assert len(notifications) == 1
    notification_id = notifications[0].id
    assert "+16502532222" == notifications[0].to
    assert resp_json["id"] == str(notification_id)
    assert mocked.called


@pytest.mark.parametrize(
    "notification_type, key_send_to, send_to",
    [
        ("sms", "phone_number", "6502532222"),
        ("email", "email_address", "sample@email.com"),
    ],
)
@freeze_time("2017-05-14 14:00:00")
def test_post_notification_with_scheduled_for(client, notify_db_session, notification_type, key_send_to, send_to):
    service = create_service(
        service_name=str(uuid.uuid4()),
        service_permissions=[EMAIL_TYPE, SMS_TYPE, SCHEDULE_NOTIFICATIONS],
    )
    template = create_template(service=service, template_type=notification_type)
    data = {
        key_send_to: send_to,
        "template_id": str(template.id) if notification_type == EMAIL_TYPE else str(template.id),
        "scheduled_for": "2017-05-14 14:15",
    }
    auth_header = create_authorization_header(service_id=service.id)

    response = client.post(
        "/v2/notifications/{}".format(notification_type),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    scheduled_notification = ScheduledNotification.query.filter_by(notification_id=resp_json["id"]).all()
    assert len(scheduled_notification) == 1
    assert resp_json["id"] == str(scheduled_notification[0].notification_id)
    assert resp_json["scheduled_for"] == "2017-05-14 14:15"


@pytest.mark.parametrize(
    "notification_type, key_send_to, send_to",
    [
        ("sms", "phone_number", "6502532222"),
        ("email", "email_address", "sample@email.com"),
    ],
)
@freeze_time("2017-05-14 14:00:00")
def test_post_notification_raises_bad_request_if_service_not_invited_to_schedule(
    client,
    sample_template,
    sample_email_template,
    notification_type,
    key_send_to,
    send_to,
):
    data = {
        key_send_to: send_to,
        "template_id": str(sample_email_template.id) if notification_type == EMAIL_TYPE else str(sample_template.id),
        "scheduled_for": "2017-05-14 14:15",
    }
    auth_header = create_authorization_header(service_id=sample_template.service_id)

    response = client.post(
        "/v2/notifications/{}".format(notification_type),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": "Cannot schedule notifications (this feature is invite-only)",
        }
    ]


def test_post_notification_raises_bad_request_if_not_valid_notification_type(client, sample_service):
    auth_header = create_authorization_header(service_id=sample_service.id)
    response = client.post(
        "/v2/notifications/foo",
        data="{}",
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 404
    error_json = json.loads(response.get_data(as_text=True))
    assert "The requested URL was not found on the server." in error_json["message"]


@pytest.mark.parametrize("notification_type", ["sms", "email"])
def test_post_notification_with_wrong_type_of_sender(
    client, sample_template, sample_email_template, notification_type, fake_uuid
):
    if notification_type == EMAIL_TYPE:
        template = sample_email_template
        form_label = "sms_sender_id"
        data = {
            "email_address": "test@test.com",
            "template_id": str(sample_email_template.id),
            form_label: fake_uuid,
        }
    elif notification_type == SMS_TYPE:
        template = sample_template
        form_label = "email_reply_to_id"
        data = {
            "phone_number": "+16502532222",
            "template_id": str(template.id),
            form_label: fake_uuid,
        }
    auth_header = create_authorization_header(service_id=template.service_id)

    response = client.post(
        path="/v2/notifications/{}".format(notification_type),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert "Additional properties are not allowed ({} was unexpected)".format(form_label) in resp_json["errors"][0]["message"]
    assert "ValidationError" in resp_json["errors"][0]["error"]


def test_post_email_notification_with_valid_reply_to_id_returns_201(notify_api, client, sample_email_template, mocker):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    reply_to_email = create_reply_to_email(sample_email_template.service, "test@test.com")
    mocked = mocker.patch("app.celery.provider_tasks.deliver_email.apply_async")
    data = {
        "email_address": sample_email_template.service.users[0].email_address,
        "template_id": sample_email_template.id,
        "email_reply_to_id": reply_to_email.id,
    }
    auth_header = create_authorization_header(service_id=sample_email_template.service_id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_email_response) == resp_json
    notification = Notification.query.first()
    assert notification.reply_to_text == "test@test.com"
    assert resp_json["id"] == str(notification.id)
    assert mocked.called

    assert notification.reply_to_text == reply_to_email.email_address


def test_post_email_notification_with_invalid_reply_to_id_returns_400(client, sample_email_template, mocker, fake_uuid):
    mocker.patch("app.celery.provider_tasks.deliver_email.apply_async")
    data = {
        "email_address": sample_email_template.service.users[0].email_address,
        "template_id": sample_email_template.id,
        "email_reply_to_id": fake_uuid,
    }
    auth_header = create_authorization_header(service_id=sample_email_template.service_id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert (
        "email_reply_to_id {} does not exist in database for service id {}".format(fake_uuid, sample_email_template.service_id)
        in resp_json["errors"][0]["message"]
    )
    assert "BadRequestError" in resp_json["errors"][0]["error"]


def test_post_email_notification_with_archived_reply_to_id_returns_400(client, sample_email_template, mocker):
    archived_reply_to = create_reply_to_email(
        sample_email_template.service,
        "reply_to@test.com",
        is_default=False,
        archived=True,
    )
    mocker.patch("app.celery.provider_tasks.deliver_email.apply_async")
    data = {
        "email_address": "test@test.com",
        "template_id": sample_email_template.id,
        "email_reply_to_id": archived_reply_to.id,
    }
    auth_header = create_authorization_header(service_id=sample_email_template.service_id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert (
        "email_reply_to_id {} does not exist in database for service id {}".format(
            archived_reply_to.id, sample_email_template.service_id
        )
        in resp_json["errors"][0]["message"]
    )
    assert "BadRequestError" in resp_json["errors"][0]["error"]


@pytest.mark.parametrize(
    "filename, file_data, sending_method",
    [
        ("good name.txt", "VGV4dCBjb250ZW50IGhlcmU=", "attach"),
        ("good name.txt", "VGV4dCBjb250ZW50IGhlcmU=", "link"),
    ],
)
def test_post_notification_with_document_upload(
    notify_api, client, notify_db_session, mocker, filename, file_data, sending_method
):
    notify_api.config["FF_NOTIFICATION_CELERY_PERSISTENCE"] = False
    service = create_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
    content = "See attached file."
    if sending_method == "link":
        content = "Document: ((document))"
    template = create_template(service=service, template_type="email", content=content)

    statsd_mock = mocker.patch("app.v2.notifications.post_notifications.statsd_client")
    mocker.patch("app.celery.provider_tasks.deliver_email.apply_async")
    document_download_mock = mocker.patch("app.v2.notifications.post_notifications.document_download_client.upload_document")
    document_response = document_download_response({"sending_method": sending_method, "mime_type": "text/plain"})
    document_download_mock.return_value = document_response
    decoded_file = base64.b64decode(file_data)

    data = {
        "email_address": service.users[0].email_address,
        "template_id": template.id,
        "personalisation": {
            "document": {
                "file": file_data,
                "filename": filename,
                "sending_method": sending_method,
            }
        },
    }

    auth_header = create_authorization_header(service_id=service.id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 201, response.get_data(as_text=True)
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_email_response) == resp_json
    document_download_mock.assert_called_once_with(
        service.id,
        {"file": decoded_file, "filename": filename, "sending_method": sending_method},
    )

    notification = Notification.query.one()
    assert notification.status == NOTIFICATION_CREATED
    assert notification.personalisation == {"document": document_response}

    if sending_method == "link":
        assert resp_json["content"]["body"] == f"Document: {document_response}"
    else:
        assert resp_json["content"]["body"] == "See attached file."

    assert statsd_mock.incr.call_args_list == [
        call("attachments.nb-attachments.count-1"),
        call("attachments.nb-attachments", count=1),
        call(f"attachments.services.{service.id}", count=1),
        call(f"attachments.templates.{template.id}", count=1),
        call(f"attachments.sending-method.{sending_method}"),
        call("attachments.file-type.text/plain"),
        call("attachments.file-size.0-1mb"),
    ]


@pytest.mark.parametrize(
    "filename, file_data, sending_method",
    [
        ("", "VGV4dCBjb250ZW50IGhlcmU=", "attach"),
        ("1", "VGV4dCBjb250ZW50IGhlcmU=", "attach"),
    ],
)
def test_post_notification_with_document_upload_bad_filename(client, notify_db_session, filename, file_data, sending_method):
    service = create_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
    content = "See attached file."
    template = create_template(service=service, template_type="email", content=content)
    data = {
        "email_address": service.users[0].email_address,
        "template_id": template.id,
        "personalisation": {
            "document": {
                "file": file_data,
                "filename": filename,
                "sending_method": sending_method,
            }
        },
    }

    auth_header = create_authorization_header(service_id=service.id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert "ValidationError" in resp_json["errors"][0]["error"]
    assert filename in resp_json["errors"][0]["message"]
    assert "too short" in resp_json["errors"][0]["message"]


def test_post_notification_with_document_upload_long_filename(
    client,
    notify_db_session,
):
    service = create_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
    content = "See attached file."
    template = create_template(service=service, template_type="email", content=content)
    file_data = "VGV4dCBjb250ZW50IGhlcmU="
    filename = "a" * 256
    sending_method = "attach"

    data = {
        "email_address": service.users[0].email_address,
        "template_id": template.id,
        "personalisation": {
            "document": {
                "file": file_data,
                "filename": filename,
                "sending_method": sending_method,
            }
        },
    }

    auth_header = create_authorization_header(service_id=service.id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert "ValidationError" in resp_json["errors"][0]["error"]
    assert filename in resp_json["errors"][0]["message"]
    assert "too long" in resp_json["errors"][0]["message"]


@pytest.mark.parametrize(
    "file_data, sending_method",
    [
        ("VGV4dCBjb250ZW50IGhlcmU=", "attach"),
    ],
)
def test_post_notification_with_document_upload_filename_required_check(client, notify_db_session, file_data, sending_method):
    service = create_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
    content = "See attached file."
    template = create_template(service=service, template_type="email", content=content)
    data = {
        "email_address": service.users[0].email_address,
        "template_id": template.id,
        "personalisation": {"document": {"file": file_data, "sending_method": sending_method}},
    }

    auth_header = create_authorization_header(service_id=service.id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert "ValidationError" in resp_json["errors"][0]["error"]
    assert "filename is a required property" in resp_json["errors"][0]["message"]


@pytest.mark.parametrize(
    "file_data",
    [
        ("VGV4dCBjb250ZW50IGhlcmU="),
    ],
)
def test_post_notification_with_document_upload_missing_sending_method(
    client,
    notify_db_session,
    file_data,
):
    service = create_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
    content = "See attached file."
    template = create_template(service=service, template_type="email", content=content)
    data = {
        "email_address": service.users[0].email_address,
        "template_id": template.id,
        "personalisation": {"document": {"file": file_data}},
    }

    auth_header = create_authorization_header(service_id=service.id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert "ValidationError" in resp_json["errors"][0]["error"]
    assert "sending_method is a required property" in resp_json["errors"][0]["message"]


@pytest.mark.parametrize(
    "file_data, sending_method, filename",
    [
        ("VGV4dCBjb250ZW50IGhlcmU=", "attch", "1.txt"),
    ],
)
def test_post_notification_with_document_upload_bad_sending_method(
    client, notify_db_session, file_data, sending_method, filename
):
    service = create_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
    content = "See attached file."
    template = create_template(service=service, template_type="email", content=content)
    data = {
        "email_address": service.users[0].email_address,
        "template_id": template.id,
        "personalisation": {
            "document": {
                "file": file_data,
                "filename": filename,
                "sending_method": sending_method,
            }
        },
    }

    auth_header = create_authorization_header(service_id=service.id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert f"personalisation {sending_method} is not one of [attach, link]" in resp_json["errors"][0]["message"]


@pytest.mark.parametrize(
    "file_data, message",
    [
        ("abc", "Incorrect padding"),
        ("🤡", "string argument should contain only ASCII characters"),
    ],
)
def test_post_notification_with_document_upload_not_base64_file(
    client,
    notify_db_session,
    file_data,
    message,
):
    service = create_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
    content = "See attached file."
    template = create_template(service=service, template_type="email", content=content)
    data = {
        "email_address": service.users[0].email_address,
        "template_id": template.id,
        "personalisation": {
            "document": {
                "file": file_data,
                "sending_method": "attach",
                "filename": "1.txt",
            }
        },
    }

    auth_header = create_authorization_header(service_id=service.id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert f"{message} : Error decoding base64 field" in resp_json["errors"][0]["message"]


def test_post_notification_with_document_upload_simulated(client, notify_db_session, mocker):
    service = create_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
    template = create_template(service=service, template_type="email", content="Document: ((document))")

    mocker.patch("app.celery.provider_tasks.deliver_email.apply_async")
    document_download_mock = mocker.patch("app.v2.notifications.post_notifications.document_download_client")
    document_download_mock.get_upload_url.return_value = "https://document-url"

    data = {
        "email_address": "simulate-delivered@notification.canada.ca",
        "template_id": template.id,
        "personalisation": {"document": {"file": "abababab", "sending_method": "link"}},
    }

    auth_header = create_authorization_header(service_id=service.id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_email_response) == resp_json

    assert resp_json["content"]["body"] == "Document: https://document-url/test-document"


def test_post_notification_without_document_upload_permission(client, notify_db_session, mocker):
    service = create_service(service_permissions=[EMAIL_TYPE])
    template = create_template(service=service, template_type="email", content="Document: ((document))")

    mocker.patch("app.celery.provider_tasks.deliver_email.apply_async")
    document_download_mock = mocker.patch("app.v2.notifications.post_notifications.document_download_client")
    document_download_mock.upload_document.return_value = document_download_response()

    data = {
        "email_address": service.users[0].email_address,
        "template_id": template.id,
        "personalisation": {"document": {"file": "abababab"}},
    }

    auth_header = create_authorization_header(service_id=service.id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400


def test_post_notification_returns_400_when_get_json_throws_exception(client, sample_email_template):
    auth_header = create_authorization_header(service_id=sample_email_template.service_id)
    response = client.post(
        path="v2/notifications/email",
        data="[",
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert response.status_code == 400


@pytest.mark.parametrize("args", [{}, {"rows": [1, 2], "csv": "foo"}], ids=["no args", "both args"])
def test_post_bulk_with_invalid_data_arguments(
    client,
    sample_email_template,
    args,
):
    data = {"name": "job_name", "template_id": str(sample_email_template.id)} | args

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=sample_email_template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": "You should specify either rows or csv",
        }
    ]


def test_post_bulk_with_invalid_reply_to_id(client, sample_email_template):
    data = {
        "name": "job_name",
        "template_id": str(sample_email_template.id),
        "rows": [["email address"], ["bob@example.com"]],
        "reply_to_id": "foo",
    }

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=sample_email_template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [
        {
            "error": "ValidationError",
            "message": "reply_to_id is not a valid UUID",
        }
    ]


def test_post_bulk_with_non_existing_reply_to_id_for_email(client, sample_email_template, fake_uuid):
    data = {
        "name": "job_name",
        "template_id": str(sample_email_template.id),
        "rows": [["email address"], ["bob@example.com"]],
        "reply_to_id": fake_uuid,
    }

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=sample_email_template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": f"email_reply_to_id {fake_uuid} does not exist in database for service id {sample_email_template.service_id}",
        }
    ]


def test_post_bulk_with_non_existing_reply_to_id_for_sms(client, sms_code_template, fake_uuid):
    data = {
        "name": "job_name",
        "template_id": str(sms_code_template.id),
        "rows": [["phone number", "verify_code"], ["bob@example.com", "123"]],
        "reply_to_id": fake_uuid,
    }

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=sms_code_template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": f"sms_sender_id {fake_uuid} does not exist in database for service id {sms_code_template.service_id}",
        }
    ]


def test_post_bulk_flags_if_name_is_missing(client, sample_email_template):
    data = {"template_id": str(sample_email_template.id), "csv": "foo"}

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=sample_email_template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [{"error": "ValidationError", "message": "name is a required property"}]


@pytest.mark.parametrize(
    "scheduled_for, expected_message",
    [
        (42, "scheduled_for 42 is not of type string, null"),
        (
            "foo",
            "scheduled_for datetime format is invalid. It must be a valid "
            "ISO8601 date time format, "
            "https://en.wikipedia.org/wiki/ISO_8601",
        ),
        ("2016-01-01T10:04:00", "scheduled_for datetime cannot be in the past"),
        ("2016-01-05T10:06:00", "scheduled_for datetime can only be up to 96 hours in the future"),
    ],
)
@freeze_time("2016-01-01 10:05:00")
def test_post_bulk_with_invalid_scheduled_for(client, sample_email_template, scheduled_for, expected_message):
    data = {"name": "job_name", "template_id": str(sample_email_template.id), "scheduled_for": scheduled_for, "rows": [1, 2]}

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=sample_email_template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [{"error": "ValidationError", "message": expected_message}]


def test_post_bulk_with_non_existing_template(client, fake_uuid, sample_email_template):
    data = {"name": "job_name", "template_id": fake_uuid, "rows": [1, 2]}

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=sample_email_template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [{"error": "BadRequestError", "message": "Template not found"}]


def test_post_bulk_with_archived_template(client, fake_uuid, notify_db, notify_db_session):
    template = sample_template(notify_db, notify_db_session, archived=True)
    data = {"name": "job_name", "template_id": template.id, "rows": [1, 2]}

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [{"error": "BadRequestError", "message": f"Template {template.id} has been deleted"}]


@pytest.mark.parametrize(
    "permission_type, notification_type, expected_error",
    [
        ("email", "sms", "text messages"),
        ("sms", "email", "emails"),
    ],
)
def test_post_bulk_returns_400_if_not_allowed_to_send_notification_type(
    notify_db_session,
    client,
    permission_type,
    notification_type,
    expected_error,
):
    service = create_service(service_permissions=[permission_type])
    sample_template_without_permission = create_template(service=service, template_type=notification_type)
    data = {"name": "job_name", "template_id": sample_template_without_permission.id, "rows": [1, 2]}
    auth_header = create_authorization_header(service_id=sample_template_without_permission.service.id)

    response = client.post(
        path="/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 400
    assert response.headers["Content-type"] == "application/json"

    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["status_code"] == 400
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": f"Service is not allowed to send {expected_error}",
        }
    ]


@pytest.mark.parametrize("data_type", ["rows", "csv"])
@pytest.mark.parametrize(
    "template_type, content, row_header, expected_error",
    [
        ("email", "Hello!", ["foo"], "email address"),
        ("email", "Hello ((name))!", ["foo"], "email address, name"),
        ("sms", "Hello ((name))!", ["foo"], "name, phone number"),
        ("sms", "Hello ((name))!", ["foo"], "name, phone number"),
        ("sms", "Hello ((name))!", ["name"], "phone number"),
        ("sms", "Hello ((name))!", ["NAME"], "phone number"),
    ],
)
def test_post_bulk_flags_missing_column_headers(
    client, notify_db, notify_db_session, data_type, template_type, content, row_header, expected_error
):
    template = sample_template(notify_db, notify_db_session, content=content, template_type=template_type)
    data = {"name": "job_name", "template_id": template.id}
    rows = [row_header, ["bar"]]
    if data_type == "csv":
        data["csv"] = rows_to_csv(rows)
    else:
        data["rows"] = rows

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [{"error": "BadRequestError", "message": f"Missing column headers: {expected_error}"}]


@pytest.mark.parametrize(
    "template_type, content, row_header, expected_error",
    [
        (
            "email",
            "Hello!",
            ["email address", "email address"],
            "email address",
        ),
        (
            "email",
            "Hello ((name))!",
            ["email address", "email_address", "name"],
            "email address, email_address",
        ),
        ("sms", "Hello!", ["phone number", "phone number"], "phone number"),
        (
            "sms",
            "Hello!",
            ["phone number", "phone_number"],
            "phone number, phone_number",
        ),
        (
            "sms",
            "Hello ((name))!",
            ["phone number", "phone_number", "name"],
            "phone number, phone_number",
        ),
    ],
)
def test_post_bulk_flags_duplicate_recipient_column_headers(
    client,
    notify_db,
    notify_db_session,
    template_type,
    content,
    row_header,
    expected_error,
):
    template = sample_template(notify_db, notify_db_session, content=content, template_type=template_type)
    data = {"name": "job_name", "template_id": template.id, "rows": [row_header, ["bar"]]}

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [{"error": "BadRequestError", "message": f"Duplicate column headers: {expected_error}"}]


def test_post_bulk_flags_too_many_rows(client, sample_email_template, notify_api):
    data = {
        "name": "job_name",
        "template_id": sample_email_template.id,
        "csv": rows_to_csv([["email address"], ["foo@example.com"], ["bar@example.com"]]),
    }

    with set_config(notify_api, "CSV_MAX_ROWS", 1):
        response = client.post(
            "/v2/notifications/bulk",
            data=json.dumps(data),
            headers=[
                ("Content-Type", "application/json"),
                create_authorization_header(service_id=sample_email_template.service_id),
            ],
        )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": "Too many rows. Maximum number of rows allowed is 1",
        }
    ]


def test_post_bulk_flags_recipient_not_in_safelist_with_team_api_key(client, sample_email_template):
    data = {
        "name": "job_name",
        "template_id": sample_email_template.id,
        "csv": rows_to_csv([["email address"], ["foo@example.com"], ["bar@example.com"]]),
    }

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[
            ("Content-Type", "application/json"),
            create_authorization_header(service_id=sample_email_template.service_id, key_type="team"),
        ],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": "You cannot send to these recipients because you used a team and safelist API key.",
        }
    ]


def test_post_bulk_flags_recipient_not_in_safelist_with_restricted_service(client, notify_db, notify_db_session):
    service = create_service(restricted=True)
    template = sample_template(notify_db, notify_db_session, service=service, template_type="email")
    data = {
        "name": "job_name",
        "template_id": template.id,
        "csv": rows_to_csv([["email address"], ["foo@example.com"], ["bar@example.com"]]),
    }

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[
            ("Content-Type", "application/json"),
            create_authorization_header(service_id=template.service_id, key_type="team"),
        ],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": "You cannot send to these recipients because your service is in trial mode. You can only send to members of your team and your safelist.",
        }
    ]


def test_post_bulk_flags_not_enough_remaining_messages(client, notify_db, notify_db_session, mocker):
    service = create_service(message_limit=10)
    template = sample_template(notify_db, notify_db_session, service=service, template_type="email")
    messages_count_mock = mocker.patch("app.v2.notifications.post_notifications.fetch_todays_total_message_count", return_value=9)
    data = {
        "name": "job_name",
        "template_id": template.id,
        "csv": rows_to_csv([["email address"], ["foo@example.com"], ["bar@example.com"]]),
    }

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": "You only have 1 remaining messages before you reach your daily limit. You've tried to send 2 messages.",
        }
    ]
    messages_count_mock.assert_called_once()


@pytest.mark.parametrize("data_type", ["rows", "csv"])
def test_post_bulk_flags_rows_with_errors(client, notify_db, notify_db_session, data_type):
    template = sample_template(notify_db, notify_db_session, template_type="email", content="Hello ((name))")
    data = {"name": "job_name", "template_id": template.id}
    rows = [
        ["email address", "name"],
        ["foo@example.com", "Foo"],
        ["bar@example.com"],
        ["nope", "nope"],
        ["baz@example.com", ""],
        ["baz@example.com", " "],
    ]
    if data_type == "csv":
        data["csv"] = rows_to_csv(rows)
    else:
        data["rows"] = rows

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=template.service_id)],
    )

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json["errors"] == [
        {
            "error": "BadRequestError",
            "message": "Some rows have errors. Row 1 - `name`: Missing. Row 2 - `email address`: invalid recipient. Row 3 - `name`: Missing. Row 4 - `name`: Missing.",
        }
    ]


@pytest.mark.parametrize("data_type", ["rows", "csv"])
@pytest.mark.parametrize("is_scheduled", [True, False])
@pytest.mark.parametrize("use_sender_id", [True, False])
@pytest.mark.parametrize("has_default_reply_to", [True, False])
def test_post_bulk_creates_job_and_dispatches_celery_task(
    client, sample_email_template, mocker, notify_user, notify_api, data_type, is_scheduled, use_sender_id, has_default_reply_to
):
    data = {"name": "job_name", "template_id": sample_email_template.id}
    rows = [["email address"], ["foo@example.com"]]
    if data_type == "csv":
        data["csv"] = rows_to_csv(rows)
    else:
        data["rows"] = rows

    if is_scheduled:
        scheduled_for = datetime.utcnow() + timedelta(days=1)
        data["scheduled_for"] = scheduled_for.isoformat()
    if has_default_reply_to:
        create_reply_to_email(sample_email_template.service, "test@test.com")
    if use_sender_id:
        reply_to_email = create_reply_to_email(sample_email_template.service, "custom@test.com", is_default=False)
        data["reply_to_id"] = reply_to_email.id

    api_key = create_api_key(service=sample_email_template.service)
    job_id = str(uuid.uuid4())
    upload_to_s3 = mocker.patch("app.v2.notifications.post_notifications.upload_job_to_s3", return_value=job_id)
    process_job = mocker.patch("app.v2.notifications.post_notifications.process_job.apply_async")

    response = client.post(
        "/v2/notifications/bulk",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header(service_id=sample_email_template.service_id)],
    )

    upload_to_s3.assert_called_once_with(sample_email_template.service_id, "email address\r\nfoo@example.com")
    if not is_scheduled:
        process_job.assert_called_once_with([str(job_id)], queue="job-tasks")
    else:
        process_job.assert_not_called()

    job = dao_get_job_by_id(job_id)
    assert str(job.id) == job_id
    assert job.service_id == sample_email_template.service_id
    assert job.template_id == sample_email_template.id
    assert job.notification_count == 1
    assert job.template_version == sample_email_template.version
    assert job.job_status == "scheduled" if is_scheduled else "pending"
    assert job.original_file_name == "job_name"
    if is_scheduled:
        assert job.scheduled_for == scheduled_for
    else:
        assert job.scheduled_for is None
    assert job.api_key_id == api_key.id
    if use_sender_id:
        assert job.sender_id == reply_to_email.id
    else:
        assert job.sender_id is None

    assert response.status_code == 201

    assert json.loads(response.get_data(as_text=True)) == {
        "data": {
            "api_key": {
                "id": str(api_key.id),
                "key_type": "normal",
                "name": api_key.name,
            },
            "archived": False,
            "created_at": f"{job.created_at.isoformat()}+00:00",
            "created_by": {"id": str(notify_user.id), "name": notify_user.name},
            "id": job_id,
            "job_status": "scheduled" if is_scheduled else "pending",
            "notification_count": 1,
            "original_file_name": "job_name",
            "processing_finished": None,
            "processing_started": None,
            "scheduled_for": f"{scheduled_for.isoformat()}+00:00" if is_scheduled else None,
            "service": str(sample_email_template.service_id),
            "service_name": {"name": sample_email_template.service.name},
            "template": str(sample_email_template.id),
            "template_version": sample_email_template.version,
            "updated_at": None,
            "sender_id": str(reply_to_email.id) if use_sender_id else None,
        }
    }
