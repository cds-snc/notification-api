import json
from datetime import datetime

import pytest
import requests_mock
from freezegun import freeze_time
from tests.app.db import (
    create_complaint,
    create_notification,
    create_service,
    create_service_callback_api,
    create_template,
    save_notification,
)
from tests.conftest import set_config_values

from app import DATETIME_FORMAT, signer_complaint, signer_delivery_status
from app.celery.service_callback_tasks import (
    _calculate_callback_retry_countdown,
    send_complaint_to_service,
    send_delivery_status_to_service,
)


@pytest.mark.parametrize("notification_type", ["email", "letter", "sms"])
def test_send_delivery_status_to_service_post_https_request_to_service_with_signed_data(notify_db_session, notification_type):
    callback_api, template = _set_up_test_data(notification_type, "delivery_status")
    datestr = datetime(2017, 6, 20)

    notification = save_notification(
        create_notification(
            template=template,
            created_at=datestr,
            updated_at=datestr,
            sent_at=datestr,
            status="sent",
        )
    )
    signed_status_update = _set_up_data_for_status_update(callback_api, notification)
    with requests_mock.Mocker() as request_mock:
        request_mock.post(callback_api.url, json={}, status_code=200)
        send_delivery_status_to_service(
            notification.id, signed_status_update=signed_status_update, service_id=notification.service_id
        )

    mock_data = {
        "id": str(notification.id),
        "reference": notification.client_reference,
        "to": notification.to,
        "status": notification.status,
        "status_description": notification.formatted_status,
        "provider_response": notification.provider_response,
        "created_at": datestr.strftime(DATETIME_FORMAT),
        "completed_at": datestr.strftime(DATETIME_FORMAT),
        "sent_at": datestr.strftime(DATETIME_FORMAT),
        "notification_type": notification_type,
    }

    assert request_mock.call_count == 1
    assert request_mock.request_history[0].url == callback_api.url
    assert request_mock.request_history[0].method == "POST"
    assert request_mock.request_history[0].text == json.dumps(mock_data)
    assert request_mock.request_history[0].headers["Content-type"] == "application/json"
    assert request_mock.request_history[0].headers["Authorization"] == "Bearer {}".format(callback_api.bearer_token)


def test_send_complaint_to_service_posts_https_request_to_service_with_signed_data(
    notify_db_session,
):
    with freeze_time("2001-01-01T12:00:00"):
        callback_api, template = _set_up_test_data("email", "complaint")

        notification = create_notification(template=template)
        complaint = create_complaint(service=template.service, notification=notification)
        complaint_data = _set_up_data_for_complaint(callback_api, complaint, notification)
        with requests_mock.Mocker() as request_mock:
            request_mock.post(callback_api.url, json={}, status_code=200)
            send_complaint_to_service(complaint_data, notification.service_id)

        mock_data = {
            "notification_id": str(notification.id),
            "complaint_id": str(complaint.id),
            "reference": notification.client_reference,
            "to": notification.to,
            "complaint_date": datetime.utcnow().strftime(DATETIME_FORMAT),
        }

        assert request_mock.call_count == 1
        assert request_mock.request_history[0].url == callback_api.url
        assert request_mock.request_history[0].method == "POST"
        assert request_mock.request_history[0].text == json.dumps(mock_data)
        assert request_mock.request_history[0].headers["Content-type"] == "application/json"
        assert request_mock.request_history[0].headers["Authorization"] == "Bearer {}".format(callback_api.bearer_token)


@pytest.mark.parametrize("notification_type", ["email", "letter", "sms"])
@pytest.mark.parametrize("status_code", [429, 500, 503])
def test__send_data_to_service_callback_api_retries_if_request_returns_error_code_with_signed_data(
    notify_db_session, mocker, notification_type, status_code
):
    callback_api, template = _set_up_test_data(notification_type, "delivery_status")
    datestr = datetime(2017, 6, 20)
    notification = save_notification(
        create_notification(
            template=template,
            created_at=datestr,
            updated_at=datestr,
            sent_at=datestr,
            status="sent",
        )
    )
    signed_data = _set_up_data_for_status_update(callback_api, notification)
    mocked = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.retry")
    mocker.patch("app.celery.service_callback_tasks.random.uniform", return_value=5)
    with requests_mock.Mocker() as request_mock:
        request_mock.post(callback_api.url, json={}, status_code=status_code)
        send_delivery_status_to_service(notification.id, signed_status_update=signed_data, service_id=notification.service_id)

    assert mocked.call_count == 1
    assert mocked.call_args[1]["queue"] == "service-callbacks-retry"
    assert mocked.call_args[1]["countdown"] == 5


def test_send_delivery_status_to_service_suspends_callback_and_sends_email_when_retries_exhausted(
    notify_db_session,
    notify_api,
    mocker,
):
    callback_api, template = _set_up_test_data("email", "delivery_status")
    datestr = datetime(2017, 6, 20)
    notification = save_notification(
        create_notification(
            template=template,
            created_at=datestr,
            updated_at=datestr,
            sent_at=datestr,
            status="sent",
        )
    )
    signed_data = _set_up_data_for_status_update(callback_api, notification)

    mocker.patch(
        "app.celery.service_callback_tasks.send_delivery_status_to_service.retry",
        side_effect=send_delivery_status_to_service.MaxRetriesExceededError(),
    )
    mocker.patch("app.celery.service_callback_tasks.random.uniform", return_value=5)
    mocked_suspend = mocker.patch(
        "app.celery.service_callback_tasks.suspend_unsuspend_service_callback_api",
        return_value=callback_api,
    )
    mocked_send_task = mocker.patch("app.celery.service_callback_tasks.notify_celery.send_task")

    with requests_mock.Mocker() as request_mock:
        request_mock.post(callback_api.url, json={}, status_code=500)
        send_delivery_status_to_service(notification.id, signed_status_update=signed_data, service_id=notification.service_id)

    mocked_suspend.assert_called_once_with(
        callback_api,
        updated_by_id=notify_api.config["NOTIFY_USER_ID"],
        suspend=True,
        failed_callback_url=callback_api.url,
    )

    mocked_send_task.assert_called_once_with(
        "send-service-callback-suspension-email",
        kwargs={"service_id": str(notification.service_id)},
        queue="notify-internal-tasks",
    )


def test_send_delivery_status_to_service_does_not_send_suspension_email_if_callback_already_suspended(
    notify_db_session,
    mocker,
):
    service = create_service(restricted=True)
    template = create_template(service=service, template_type="email", subject="Hello")
    callback_api = create_service_callback_api(
        service=service,
        url="https://some.service.gov.uk/",
        bearer_token="something_unique",
        callback_type="delivery_status",
        is_suspended=True,
    )

    datestr = datetime(2017, 6, 20)
    notification = save_notification(
        create_notification(
            template=template,
            created_at=datestr,
            updated_at=datestr,
            sent_at=datestr,
            status="sent",
        )
    )
    signed_data = _set_up_data_for_status_update(callback_api, notification)

    mocked_retry = mocker.patch(
        "app.celery.service_callback_tasks.send_delivery_status_to_service.retry",
        side_effect=send_delivery_status_to_service.MaxRetriesExceededError(),
    )
    mocker.patch("app.celery.service_callback_tasks.random.uniform", return_value=5)
    mocked_suspend = mocker.patch("app.celery.service_callback_tasks.suspend_unsuspend_service_callback_api")
    mocked_send_task = mocker.patch("app.celery.service_callback_tasks.notify_celery.send_task")

    with requests_mock.Mocker() as request_mock:
        request_mock.post(callback_api.url, json={}, status_code=500)
        send_delivery_status_to_service(notification.id, signed_status_update=signed_data, service_id=notification.service_id)

    assert request_mock.call_count == 0
    mocked_retry.assert_not_called()
    mocked_suspend.assert_not_called()
    mocked_send_task.assert_not_called()


def test_send_delivery_status_to_service_rebinds_to_current_callback_when_callback_url_changes(
    notify_db_session,
    mocker,
):
    callback_api, template = _set_up_test_data("email", "delivery_status")
    datestr = datetime(2017, 6, 20)
    notification = save_notification(
        create_notification(
            template=template,
            created_at=datestr,
            updated_at=datestr,
            sent_at=datestr,
            status="sent",
        )
    )
    signed_data = _set_up_data_for_status_update(callback_api, notification)
    new_url = "https://new.service.gov.uk/"
    new_token = "new-bearer-token"

    callback_api.url = new_url
    callback_api.bearer_token = new_token
    notify_db_session.commit()

    mocked_retry = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.retry")
    mocked_send_task = mocker.patch("app.celery.service_callback_tasks.notify_celery.send_task")
    mocked_suspend = mocker.patch("app.celery.service_callback_tasks.suspend_unsuspend_service_callback_api")

    with requests_mock.Mocker() as request_mock:
        request_mock.post(new_url, json={}, status_code=200)
        send_delivery_status_to_service(notification.id, signed_status_update=signed_data, service_id=notification.service_id)

    assert request_mock.call_count == 1
    assert request_mock.request_history[0].url == new_url
    assert request_mock.request_history[0].headers["Authorization"] == f"Bearer {new_token}"
    mocked_retry.assert_not_called()
    mocked_suspend.assert_not_called()
    mocked_send_task.assert_not_called()


def test_send_delivery_status_to_service_suspends_current_callback_when_stale_payload_retries_exhausted(
    notify_db_session,
    notify_api,
    mocker,
):
    callback_api, template = _set_up_test_data("email", "delivery_status")
    datestr = datetime(2017, 6, 20)
    notification = save_notification(
        create_notification(
            template=template,
            created_at=datestr,
            updated_at=datestr,
            sent_at=datestr,
            status="sent",
        )
    )
    signed_data = _set_up_data_for_status_update(callback_api, notification)

    stale_url = callback_api.url
    new_url = "https://new.service.gov.uk/"

    callback_api.url = new_url
    notify_db_session.commit()

    mocker.patch(
        "app.celery.service_callback_tasks.send_delivery_status_to_service.retry",
        side_effect=send_delivery_status_to_service.MaxRetriesExceededError(),
    )
    mocker.patch("app.celery.service_callback_tasks.random.uniform", return_value=5)
    mocked_suspend = mocker.patch(
        "app.celery.service_callback_tasks.suspend_unsuspend_service_callback_api",
        return_value=callback_api,
    )
    mocked_send_task = mocker.patch("app.celery.service_callback_tasks.notify_celery.send_task")

    with requests_mock.Mocker() as request_mock:
        request_mock.post(new_url, json={}, status_code=500)
        send_delivery_status_to_service(notification.id, signed_status_update=signed_data, service_id=notification.service_id)

    assert request_mock.call_count == 1
    assert request_mock.request_history[0].url == new_url
    mocked_suspend.assert_called_once_with(
        callback_api,
        updated_by_id=notify_api.config["NOTIFY_USER_ID"],
        suspend=True,
        failed_callback_url=new_url,
    )
    mocked_send_task.assert_called_once_with(
        "send-service-callback-suspension-email",
        kwargs={"service_id": str(notification.service_id)},
        queue="notify-internal-tasks",
    )
    assert stale_url != new_url


def test_calculate_callback_retry_countdown_uses_exponential_backoff_and_cap(notify_db_session, notify_api):
    with set_config_values(
        notify_api,
        {
            "CALLBACK_RETRY_BACKOFF_BASE_SECONDS": 5,
            "CALLBACK_RETRY_BACKOFF_MAX_SECONDS": 20,
            "CALLBACK_RETRY_JITTER_FACTOR": 0.0,
        },
    ):
        assert _calculate_callback_retry_countdown(retries=0) == 5
        assert _calculate_callback_retry_countdown(retries=1) == 10
        assert _calculate_callback_retry_countdown(retries=2) == 20
        assert _calculate_callback_retry_countdown(retries=3) == 20


def test_calculate_callback_retry_countdown_applies_jitter_with_expected_bounds(notify_db_session, notify_api, mocker):
    with set_config_values(
        notify_api,
        {
            "CALLBACK_RETRY_BACKOFF_BASE_SECONDS": 10,
            "CALLBACK_RETRY_BACKOFF_MAX_SECONDS": 300,
            "CALLBACK_RETRY_JITTER_FACTOR": 0.2,
        },
    ):
        mocked_uniform = mocker.patch("app.celery.service_callback_tasks.random.uniform", return_value=13.1)

        countdown = _calculate_callback_retry_countdown(retries=0)

        mocked_uniform.assert_called_once_with(8.0, 12.0)
        assert countdown == 13


@pytest.mark.parametrize("notification_type", ["email", "letter", "sms"])
def test__send_data_to_service_callback_api_does_not_retry_if_request_returns_404_with_signed_data(
    notify_db_session, mocker, notification_type
):
    callback_api, template = _set_up_test_data(notification_type, "delivery_status")
    datestr = datetime(2017, 6, 20)
    notification = save_notification(
        create_notification(
            template=template,
            created_at=datestr,
            updated_at=datestr,
            sent_at=datestr,
            status="sent",
        )
    )
    signed_data = _set_up_data_for_status_update(callback_api, notification)
    mocked = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.retry")
    with requests_mock.Mocker() as request_mock:
        request_mock.post(callback_api.url, json={}, status_code=404)
        send_delivery_status_to_service(notification.id, signed_status_update=signed_data, service_id=notification.service_id)

    assert mocked.call_count == 0


def test_send_delivery_status_to_service_succeeds_if_sent_at_is_none(notify_db_session, mocker):
    callback_api, template = _set_up_test_data("email", "delivery_status")
    datestr = datetime(2017, 6, 20)
    notification = save_notification(
        create_notification(
            template=template,
            created_at=datestr,
            updated_at=datestr,
            sent_at=None,
            status="technical-failure",
        )
    )
    signed_data = _set_up_data_for_status_update(callback_api, notification)
    mocked = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.retry")
    with requests_mock.Mocker() as request_mock:
        request_mock.post(callback_api.url, json={}, status_code=404)
        send_delivery_status_to_service(notification.id, signed_status_update=signed_data, service_id=notification.service_id)

    assert mocked.call_count == 0


def _set_up_test_data(notification_type, callback_type):
    service = create_service(restricted=True)
    template = create_template(service=service, template_type=notification_type, subject="Hello")
    callback_api = create_service_callback_api(
        service=service,
        url="https://some.service.gov.uk/",
        bearer_token="something_unique",
        callback_type=callback_type,
    )
    return callback_api, template


def _set_up_data_for_status_update(callback_api, notification):
    data = {
        "notification_id": str(notification.id),
        "notification_client_reference": notification.client_reference,
        "notification_to": notification.to,
        "notification_status": notification.status,
        "notification_status_description": notification.formatted_status,
        "notification_provider_response": notification.provider_response,
        "notification_created_at": notification.created_at.strftime(DATETIME_FORMAT),
        "notification_updated_at": notification.updated_at.strftime(DATETIME_FORMAT) if notification.updated_at else None,
        "notification_sent_at": notification.sent_at.strftime(DATETIME_FORMAT) if notification.sent_at else None,
        "notification_type": notification.notification_type,
        "service_callback_api_url": callback_api.url,
        "service_callback_api_bearer_token": callback_api.bearer_token,
    }
    signed_status_update = signer_delivery_status.sign(data)
    return signed_status_update


def _set_up_data_for_complaint(callback_api, complaint, notification):
    data = {
        "complaint_id": str(complaint.id),
        "notification_id": str(notification.id),
        "reference": notification.client_reference,
        "to": notification.to,
        "complaint_date": complaint.complaint_date.strftime(DATETIME_FORMAT),
        "service_callback_api_url": callback_api.url,
        "service_callback_api_bearer_token": callback_api.bearer_token,
    }
    obscured_status_update = signer_complaint.sign(data)
    return obscured_status_update
