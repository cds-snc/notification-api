import json
from datetime import datetime
from unittest.mock import Mock

import pytest
from freezegun import freeze_time
from tests.app.conftest import create_sample_notification
from tests.app.db import (
    create_notification,
    create_notification_history,
    create_service_callback_api,
    save_notification,
)
from tests.conftest import set_config

from app import annual_limit_client, bounce_rate_client, signer_complaint, statsd_client
from app.aws.mocks import (
    generate_ses_notification_callbacks,
    ses_complaint_account_suppression_list_callback_with_missing_complained_recipients,
    ses_complaint_callback,
    ses_unknown_bounce_callback,
)
from app.celery.process_ses_receipts_tasks import process_ses_results
from app.celery.research_mode_tasks import (
    ses_hard_bounce_callback,
    ses_notification_callback,
    ses_soft_bounce_callback,
)
from app.dao.notifications_dao import get_notification_by_id
from app.models import (
    NOTIFICATION_HARD_BOUNCE,
    NOTIFICATION_HARD_GENERAL,
    NOTIFICATION_HARD_NOEMAIL,
    NOTIFICATION_HARD_ONACCOUNTSUPPRESSIONLIST,
    NOTIFICATION_HARD_SUPPRESSED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SOFT_ATTACHMENTREJECTED,
    NOTIFICATION_SOFT_BOUNCE,
    NOTIFICATION_SOFT_CONTENTREJECTED,
    NOTIFICATION_SOFT_GENERAL,
    NOTIFICATION_SOFT_MAILBOXFULL,
    NOTIFICATION_SOFT_MESSAGETOOLARGE,
    NOTIFICATION_UNKNOWN_BOUNCE,
    Complaint,
    Notification,
)
from app.notifications.callbacks import create_delivery_status_callback_data
from app.notifications.notifications_ses_callback import (
    remove_emails_from_bounce,
    remove_emails_from_complaint,
)
from celery.exceptions import MaxRetriesExceededError


def test_process_ses_results(sample_email_template, mocker):
    mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))
    refs = []
    for i in range(10):
        ref = f"ref{i}"
        save_notification(
            create_notification(
                sample_email_template,
                reference=ref,
                sent_at=datetime.utcnow(),
                status="sending",
            )
        )
        refs.append(ref)

    assert process_ses_results(response=generate_ses_notification_callbacks(references=refs))


def test_process_ses_results_retry_called(sample_email_template, notify_db, mocker):
    save_notification(
        create_notification(
            sample_email_template,
            reference="ref1",
            sent_at=datetime.utcnow(),
            status="sending",
        )
    )

    mocker.patch(
        "app.dao.notifications_dao._update_notification_statuses",
        side_effect=Exception("EXPECTED"),
    )
    mocked = mocker.patch("app.celery.process_ses_receipts_tasks.process_ses_results.retry")
    process_ses_results(response=ses_notification_callback(reference="ref1"))
    assert mocked.call_count != 0


def test_process_ses_results_in_complaint(sample_email_template, mocker):
    notification = save_notification(create_notification(template=sample_email_template, reference="ref1"))
    mocked = mocker.patch("app.dao.notifications_dao.update_notification_status_by_reference")
    process_ses_results(response=ses_complaint_callback())
    assert mocked.call_count == 0
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_remove_emails_from_complaint():
    test_json = ses_complaint_callback()["Messages"][0]
    remove_emails_from_complaint(test_json)
    assert "recipient1@example.com" not in json.dumps(test_json)


def test_remove_emails_from_complaint_handles_missing_complained_receipients():
    test_json = ses_complaint_account_suppression_list_callback_with_missing_complained_recipients()["Messages"][0]
    remove_emails_from_complaint(test_json)
    assert "recipient1@example.com" not in json.dumps(test_json)


def test_remove_email_from_bounce():
    test_json = ses_hard_bounce_callback(reference="ref1")["Messages"][0]
    remove_emails_from_bounce(test_json)
    assert "bounce@simulator.amazonses.com" not in json.dumps(test_json)


def test_ses_callback_should_update_notification_status(notify_db, notify_db_session, sample_email_template, mocker):
    with freeze_time("2001-01-01T12:00:00"):
        mocker.patch("app.statsd_client.incr")
        mocker.patch("app.statsd_client.timing_with_dates")
        send_mock = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async")
        notification = create_sample_notification(
            notify_db,
            notify_db_session,
            template=sample_email_template,
            reference="ref",
            status="sending",
            sent_at=datetime.utcnow(),
        )
        callback_api = create_service_callback_api(service=sample_email_template.service, url="https://original_url.com")
        assert get_notification_by_id(notification.id).status == "sending"

        assert process_ses_results(generate_ses_notification_callbacks(references=["ref"]))
        notification = get_notification_by_id(notification.id)
        assert notification.status == "delivered"
        assert notification.provider_response is None
        statsd_client.timing_with_dates.assert_any_call("callback.ses.elapsed-time", datetime.utcnow(), notification.sent_at)
        statsd_client.incr.assert_any_call("callback.ses.delivered")
        updated_notification = Notification.query.get(notification.id)
        encrypted_data = create_delivery_status_callback_data(updated_notification, callback_api)
        send_mock.assert_called_once_with(
            [str(notification.id), encrypted_data, notification.service_id], queue="service-callbacks"
        )


def test_ses_callback_dont_change_hard_bounce_status(sample_template, mocker):
    with freeze_time("2001-01-01T12:00:00"):
        mocker.patch("app.statsd_client.incr")
        mocker.patch("app.statsd_client.timing_with_dates")
        mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async")
        mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))
        notification = save_notification(
            create_notification(
                sample_template,
                status=NOTIFICATION_PERMANENT_FAILURE,
                reference="ref",
            )
        )
        notification = get_notification_by_id(notification.id)
        assert notification.status == NOTIFICATION_PERMANENT_FAILURE
        assert process_ses_results(generate_ses_notification_callbacks(references=["ref"]))
        notification = get_notification_by_id(notification.id)
        assert notification.status == NOTIFICATION_PERMANENT_FAILURE


def test_ses_callback_should_update_notification_status_when_receiving_new_delivery_receipt(sample_email_template, mocker):
    notification = save_notification(create_notification(template=sample_email_template, reference="ref", status="delivered"))
    mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))

    assert process_ses_results(ses_hard_bounce_callback(reference="ref"))
    assert get_notification_by_id(notification.id).status == "permanent-failure"


def test_ses_callback_should_retry_if_notification_is_new(notify_db, mocker):
    mock_retry = mocker.patch("app.celery.process_ses_receipts_tasks.process_ses_results.retry")
    mock_logger = mocker.patch("app.celery.process_ses_receipts_tasks.current_app.logger.error")

    with freeze_time("2017-11-17T12:14:03.646Z"):
        assert process_ses_results(ses_notification_callback(reference="ref")) is None
        assert mock_logger.call_count == 0
        assert mock_retry.call_count == 1


def test_process_ses_receipts_tasks_exception_handling(notify_db, mocker):
    reference = "test_reference"
    mocker.patch("app.celery.process_ses_receipts_tasks.process_ses_results.retry", side_effect=MaxRetriesExceededError())
    mock_warning = mocker.patch("app.celery.process_ses_receipts_tasks.current_app.logger.error")

    with pytest.raises(Exception):
        process_ses_results(ses_notification_callback(reference))
        assert mock_warning.call_count == 2
        assert "RETRY 5: notification not found for SES reference test_reference." in mock_warning.call_args_list[0][0][0]
        assert (
            "notification not found for SES reference: test_reference. Error has persisted > number of retries. Giving up."
            in mock_warning.call_args_list[1][0][0]
        )


def test_ses_callback_should_retry_if_notification_is_missing(notify_db, mocker):
    mock_retry = mocker.patch("app.celery.process_ses_receipts_tasks.process_ses_results.retry")
    assert process_ses_results(ses_notification_callback(reference="ref")) is None
    assert mock_retry.call_count == 1


def test_ses_callback_should_give_up_after_max_tries(notify_db, mocker):
    mocker.patch(
        "app.celery.process_ses_receipts_tasks.process_ses_results.retry",
        side_effect=MaxRetriesExceededError,
    )
    mock_logger = mocker.patch("app.celery.process_ses_receipts_tasks.current_app.logger.error")

    assert process_ses_results(generate_ses_notification_callbacks(references=["ref"])) is None
    mock_logger.assert_called_with("notifications not found for SES references: ref. Giving up.")


def test_ses_callback_does_not_call_send_delivery_status_if_no_db_entry(
    notify_db, notify_db_session, sample_email_template, mocker
):
    mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))
    with freeze_time("2001-01-01T12:00:00"):
        send_mock = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async")
        notification = create_sample_notification(
            notify_db,
            notify_db_session,
            template=sample_email_template,
            reference="ref",
            status="sending",
            sent_at=datetime.utcnow(),
        )

        assert get_notification_by_id(notification.id).status == "sending"

        assert process_ses_results(generate_ses_notification_callbacks(references=["ref"]))
        notification = get_notification_by_id(notification.id)
        assert notification.status == "delivered"
        assert notification.provider_response is None

        send_mock.assert_not_called()


def test_ses_callback_should_update_multiple_notification_status_sent(
    notify_db, notify_db_session, sample_email_template, mocker
):
    send_mock = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async")
    create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference="ref1",
        sent_at=datetime.utcnow(),
        status="sending",
    )

    create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference="ref2",
        sent_at=datetime.utcnow(),
        status="sending",
    )

    create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference="ref3",
        sent_at=datetime.utcnow(),
        status="sending",
    )
    create_service_callback_api(service=sample_email_template.service, url="https://original_url.com")
    assert process_ses_results(generate_ses_notification_callbacks(references=["ref1", "ref2", "ref3"]))

    assert send_mock.called


def test_ses_callback_should_only_enqueue_failed_updates_for_retry(notify_db, notify_db_session, sample_email_template, mocker):
    mock_send = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async")
    mock_retry: Mock = mocker.patch("app.celery.process_ses_receipts_tasks.process_ses_results.retry")
    mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))
    callbacks = generate_ses_notification_callbacks(references=["ref1", "ref2", "ref3", "ref4", "ref5"])
    ids_to_retry = ["ref4", "ref5"]
    retry_args = [{"Messages": list(filter(lambda x: x["mail"]["messageId"] in ids_to_retry, callbacks["Messages"]))}]

    create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference="ref1",
        sent_at=datetime.utcnow(),
        status="sending",
    )

    create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference="ref2",
        sent_at=datetime.utcnow(),
        status="sending",
    )

    create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference="ref3",
        sent_at=datetime.utcnow(),
        status="sending",
    )
    create_service_callback_api(service=sample_email_template.service, url="https://original_url.com")
    assert process_ses_results(callbacks)
    assert mock_retry.call_args[1]["queue"] == "retry-tasks"
    assert mock_retry.call_args[1]["args"] == retry_args
    assert mock_send.call_count == 3


@pytest.mark.parametrize(
    "bounce_subtype, provider_response",
    [
        ["General", None],
        ["AttachmentRejected", "The email was rejected because of its attachments"],
    ],
)
def test_ses_callback_should_set_status_to_temporary_failure(
    notify_db,
    notify_db_session,
    sample_email_template,
    mocker,
    bounce_subtype,
    provider_response,
):
    mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))
    send_mock = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async")
    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference="ref",
        status="sending",
        sent_at=datetime.utcnow(),
    )
    create_service_callback_api(service=notification.service, url="https://original_url.com")
    assert get_notification_by_id(notification.id).status == "sending"
    assert process_ses_results(ses_soft_bounce_callback(reference="ref", bounce_subtype=bounce_subtype))

    notification = get_notification_by_id(notification.id)
    assert notification.status == "temporary-failure"
    assert notification.provider_response == provider_response
    assert send_mock.called


@pytest.mark.parametrize(
    "bounce_subtype, provider_response",
    [
        ["General", None],
        ["Suppressed", "The email address is on our email provider suppression list"],
        [
            "OnAccountSuppressionList",
            "The email address is on the GC Notify suppression list",
        ],
    ],
)
def test_ses_callback_should_set_status_to_permanent_failure(
    notify_db, notify_db_session, sample_email_template, mocker, bounce_subtype, provider_response
):
    mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))
    send_mock = mocker.patch("app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async")
    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference="ref",
        status="sending",
        sent_at=datetime.utcnow(),
    )
    create_service_callback_api(service=sample_email_template.service, url="https://original_url.com")

    assert get_notification_by_id(notification.id).status == "sending"
    assert process_ses_results(ses_hard_bounce_callback(reference="ref", bounce_subtype=bounce_subtype))

    notification = get_notification_by_id(notification.id)
    assert notification.status == "permanent-failure"
    assert notification.provider_response == provider_response
    assert send_mock.called


def test_ses_callback_should_send_on_complaint_to_user_callback_api(sample_email_template, mocker):
    send_mock = mocker.patch("app.celery.service_callback_tasks.send_complaint_to_service.apply_async")
    create_service_callback_api(
        service=sample_email_template.service,
        url="https://original_url.com",
        callback_type="complaint",
    )

    notification = save_notification(
        create_notification(
            template=sample_email_template,
            reference="ref1",
            sent_at=datetime.utcnow(),
            status="sending",
        )
    )
    response = ses_complaint_callback()
    assert process_ses_results(response)

    assert send_mock.call_count == 1
    assert signer_complaint.verify(send_mock.call_args[0][0][0]) == {
        "complaint_date": "2018-06-05T13:59:58.000000Z",
        "complaint_id": str(Complaint.query.one().id),
        "notification_id": str(notification.id),
        "reference": None,
        "service_callback_api_bearer_token": "some_super_secret",
        "service_callback_api_url": "https://original_url.com",
        "to": "recipient1@example.com",
    }


class TestBounceRates:
    @pytest.mark.parametrize(
        "bounce_subtype, expected_subtype",
        [
            ("General", NOTIFICATION_HARD_GENERAL),
            ("NoEmail", NOTIFICATION_HARD_NOEMAIL),
            ("Suppressed", NOTIFICATION_HARD_SUPPRESSED),
            ("OnAccountSuppressionList", NOTIFICATION_HARD_ONACCOUNTSUPPRESSIONLIST),
        ],
    )
    def test_ses_callback_should_update_bounce_info_new_delivery_receipt_hard_bounce(
        self, sample_email_template, mocker, bounce_subtype, expected_subtype
    ):
        mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))
        notification = save_notification(create_notification(template=sample_email_template, reference="ref", status="delivered"))

        assert process_ses_results(ses_hard_bounce_callback(reference="ref", bounce_subtype=bounce_subtype))
        assert get_notification_by_id(notification.id).feedback_type == NOTIFICATION_HARD_BOUNCE
        assert get_notification_by_id(notification.id).feedback_subtype == expected_subtype

    @pytest.mark.parametrize(
        "bounce_subtype, expected_subtype",
        [
            ("General", NOTIFICATION_SOFT_GENERAL),
            ("MailboxFull", NOTIFICATION_SOFT_MAILBOXFULL),
            ("MessageTooLarge", NOTIFICATION_SOFT_MESSAGETOOLARGE),
            ("ContentRejected", NOTIFICATION_SOFT_CONTENTREJECTED),
            ("AttachmentRejected", NOTIFICATION_SOFT_ATTACHMENTREJECTED),
        ],
    )
    def test_ses_callback_should_update_bounce_info_new_delivery_receipt_soft_bounce(
        self, sample_email_template, mocker, bounce_subtype, expected_subtype
    ):
        mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))
        notification = save_notification(create_notification(template=sample_email_template, reference="ref", status="delivered"))

        assert process_ses_results(ses_soft_bounce_callback(reference="ref", bounce_subtype=bounce_subtype))
        assert get_notification_by_id(notification.id).feedback_type == NOTIFICATION_SOFT_BOUNCE
        assert get_notification_by_id(notification.id).feedback_subtype == expected_subtype

    @pytest.mark.parametrize(
        "bounce_subtype, expected_subtype",
        [
            ("General", NOTIFICATION_HARD_GENERAL),
            ("NoEmail", NOTIFICATION_HARD_NOEMAIL),
            ("Suppressed", NOTIFICATION_HARD_SUPPRESSED),
            ("OnAccountSuppressionList", NOTIFICATION_HARD_ONACCOUNTSUPPRESSIONLIST),
        ],
    )
    def test_ses_callback_should_add_redis_key_when_delivery_receipt_is_hard_bounce(
        self, sample_email_template, mocker, bounce_subtype, expected_subtype, notify_api
    ):
        mocker.patch("app.bounce_rate_client.set_sliding_hard_bounce")
        mocker.patch("app.bounce_rate_client.set_sliding_notifications")

        notification = save_notification(create_notification(template=sample_email_template, reference="ref", status="delivered"))

        with set_config(notify_api, "REDIS_ENABLED", True):
            assert process_ses_results(ses_hard_bounce_callback(reference="ref", bounce_subtype=bounce_subtype))

            bounce_rate_client.set_sliding_hard_bounce.assert_called_with(notification.service_id, str(notification.id))
            bounce_rate_client.set_sliding_notifications.assert_not_called()

    @pytest.mark.parametrize(
        "bounce_subtype, expected_subtype",
        [
            ("General", NOTIFICATION_SOFT_GENERAL),
            ("MailboxFull", NOTIFICATION_SOFT_MAILBOXFULL),
            ("MessageTooLarge", NOTIFICATION_SOFT_MESSAGETOOLARGE),
            ("ContentRejected", NOTIFICATION_SOFT_CONTENTREJECTED),
            ("AttachmentRejected", NOTIFICATION_SOFT_ATTACHMENTREJECTED),
        ],
    )
    def test_ses_callback_should_not_add_redis_keys_when_delivery_receipt_is_soft_bounce(
        self, sample_email_template, mocker, bounce_subtype, expected_subtype, notify_api
    ):
        mocker.patch("app.bounce_rate_client.set_sliding_hard_bounce")
        mocker.patch("app.bounce_rate_client.set_sliding_notifications")
        mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))

        save_notification(create_notification(template=sample_email_template, reference="ref", status="delivered"))

        with set_config(notify_api, "REDIS_ENABLED", True):
            assert process_ses_results(ses_soft_bounce_callback(reference="ref", bounce_subtype=bounce_subtype))

            bounce_rate_client.set_sliding_hard_bounce.assert_not_called()
            bounce_rate_client.set_sliding_notifications.assert_not_called()


class TestAnnualLimits:
    def test_ses_callback_should_increment_email_delivered_when_delivery_receipt_is_delivered(
        self, notify_api, sample_email_template, mocker
    ):
        mocker.patch("app.annual_limit_client.increment_email_delivered")
        mocker.patch("app.annual_limit_client.increment_email_failed")
        mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))

        # TODO FF_ANNUAL_LIMIT removal
        with set_config(notify_api, "FF_ANNUAL_LIMIT", True):
            save_notification(create_notification(template=sample_email_template, reference="ref", status="sending"))

            assert process_ses_results(ses_notification_callback(reference="ref"))
            annual_limit_client.increment_email_delivered.assert_called_once_with(sample_email_template.service_id)
            annual_limit_client.increment_email_failed.assert_not_called()

    @pytest.mark.parametrize(
        "callback, bounce_type",
        [
            (ses_hard_bounce_callback, NOTIFICATION_HARD_BOUNCE),
            (ses_soft_bounce_callback, NOTIFICATION_SOFT_BOUNCE),
            (ses_unknown_bounce_callback, NOTIFICATION_UNKNOWN_BOUNCE),
        ],
    )
    def test_ses_callback_should_increment_email_failed_when_delivery_receipt_is_failure(
        self, notify_api, sample_email_template, mocker, callback, bounce_type
    ):
        mocker.patch("app.annual_limit_client.increment_email_failed")
        mocker.patch("app.annual_limit_client.increment_email_delivered")
        mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))

        # TODO FF_ANNUAL_LIMIT removal
        with set_config(notify_api, "FF_ANNUAL_LIMIT", True):
            save_notification(create_notification(template=sample_email_template, reference="ref", status="sending"))

            assert process_ses_results(callback(reference="ref"))
            annual_limit_client.increment_email_failed.assert_called_once_with(sample_email_template.service_id)
            annual_limit_client.increment_email_delivered.assert_not_called()

    @pytest.mark.parametrize(
        "callback, data",
        [
            (
                ses_notification_callback,
                {
                    "sms_failed_today": 0,
                    "email_failed_today": 0,
                    "sms_delivered_today": 0,
                    "email_delivered_today": 1,
                    "total_sms_fiscal_year_to_yesterday": 0,
                    "total_email_fiscal_year_to_yesterday": 0,
                },
            ),
            (
                ses_hard_bounce_callback,
                {
                    "sms_failed_today": 0,
                    "email_failed_today": 1,
                    "sms_delivered_today": 0,
                    "email_delivered_today": 0,
                    "total_sms_fiscal_year_to_yesterday": 0,
                    "total_email_fiscal_year_to_yesterday": 0,
                },
            ),
            (
                ses_soft_bounce_callback,
                {
                    "sms_failed_today": 0,
                    "email_failed_today": 1,
                    "sms_delivered_today": 0,
                    "email_delivered_today": 0,
                    "total_sms_fiscal_year_to_yesterday": 0,
                    "total_email_fiscal_year_to_yesterday": 0,
                },
            ),
        ],
    )
    def test_process_ses_results_seeds_annual_limit_notifications_when_not_seeded_today_and_doesnt_increment_when_seeding(
        self,
        callback,
        data,
        sample_email_template,
        notify_api,
        mocker,
    ):
        mocker.patch("app.annual_limit_client.increment_email_delivered")
        mocker.patch("app.annual_limit_client.increment_email_failed")
        mock_seed_annual_limit = mocker.patch("app.annual_limit_client.seed_annual_limit_notifications")

        notification = save_notification(
            create_notification(
                sample_email_template,
                reference="ref",
                sent_at=datetime.utcnow(),
                status="sending",
                sent_by="ses",
            )
        )
        with set_config(notify_api, "REDIS_ENABLED", True):
            process_ses_results(callback(reference="ref"))
            mock_seed_annual_limit.assert_called_once_with(notification.service_id, data)
            annual_limit_client.increment_email_delivered.assert_not_called()
            annual_limit_client.increment_email_failed.assert_not_called()


def test_process_ses_results_processes_complaint_from_notification_history(sample_email_template, mocker):
    """Test that complaints are processed even when the notification is only found in notification_history table."""
    # Create a notification in history but not in main table (simulating old notification that was moved)
    notification_history = create_notification_history(template=sample_email_template, reference="ref1", status="delivered")

    # Mock the fetch_notification_from_history function to return the history notification
    mock_history_fetch = mocker.patch(
        "app.celery.process_ses_receipts_tasks.fetch_notification_from_history", return_value=notification_history
    )

    # Mock the complaint handling
    mock_handle_complaint = mocker.patch(
        "app.celery.process_ses_receipts_tasks.handle_complaint", return_value=(notification_history, {"complaint_data": "test"})
    )
    mock_complaint_callback = mocker.patch("app.celery.process_ses_receipts_tasks._check_and_queue_complaint_callback_task")

    # Create a complaint receipt
    complaint_response = ses_complaint_callback()

    # Process the complaint
    result = process_ses_results(complaint_response)

    # Verify the complaint was processed using the notification from history
    assert result is True
    mock_history_fetch.assert_called_once_with("ref1")
    mock_handle_complaint.assert_called_once()
    mock_complaint_callback.assert_called_once()


def test_process_ses_results_non_complaints_are_retried_when_not_found(sample_email_template, mocker):
    """Test that non-complaint receipts are retried when notifications are not found, without checking history."""
    # Mock retry mechanism
    mock_retry = mocker.patch("app.celery.process_ses_receipts_tasks.process_ses_results.retry")

    # Mock that no notifications are found in main table
    mocker.patch("app.celery.process_ses_receipts_tasks.fetch_notifications", return_value=None)

    # Mock that history lookup is NOT called for non-complaints
    mock_history_fetch = mocker.patch("app.celery.process_ses_receipts_tasks.fetch_notification_from_history")

    # Create a non-complaint receipt (delivery receipt)
    delivery_response = ses_notification_callback(reference="ref1")

    # Process the delivery receipt
    result = process_ses_results(delivery_response)

    # Verify that:
    # 1. The function returns None (indicating retry)
    # 2. Retry was called
    # 3. History lookup was NOT called for non-complaints
    assert result is None
    mock_retry.assert_called_once()
    mock_history_fetch.assert_not_called()


def test_process_ses_results_mixed_complaint_and_non_complaint_receipts(sample_email_template, mocker):
    """Test processing mixed complaint and non-complaint receipts where some are in history."""
    # Create a notification in main table for non-complaint
    save_notification(create_notification(template=sample_email_template, reference="ref_delivery", status="sending"))

    # Create a notification in history for complaint
    notification_history = create_notification_history(
        template=sample_email_template, reference="ref_complaint", status="delivered"
    )

    # Mock functions
    mock_history_fetch = mocker.patch(
        "app.celery.process_ses_receipts_tasks.fetch_notification_from_history", return_value=notification_history
    )
    mock_handle_complaint = mocker.patch(
        "app.celery.process_ses_receipts_tasks.handle_complaint", return_value=(notification_history, {"complaint_data": "test"})
    )
    mock_complaint_callback = mocker.patch("app.celery.process_ses_receipts_tasks._check_and_queue_complaint_callback_task")
    mock_check_callback = mocker.patch("app.celery.process_ses_receipts_tasks._check_and_queue_callback_task")
    mocker.patch("app.celery.process_ses_receipts_tasks.get_annual_limit_notifications_v3", return_value=({}, False))

    # Create mixed receipts: one complaint, one delivery
    complaint_msg = ses_complaint_callback()["Messages"][0]
    complaint_msg["mail"]["messageId"] = "ref_complaint"

    delivery_msg = ses_notification_callback(reference="ref_delivery")["Messages"][0]

    mixed_response = {"Messages": [complaint_msg, delivery_msg]}

    # Process both receipts
    result = process_ses_results(mixed_response)

    # Verify both were processed correctly
    assert result is True
    mock_history_fetch.assert_called_once_with("ref_complaint")
    mock_handle_complaint.assert_called_once()
    mock_complaint_callback.assert_called_once()
    mock_check_callback.assert_called_once()  # For the delivery receipt
