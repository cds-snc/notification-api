from datetime import datetime
from unittest import mock

import pytest
from flask import json
from sqlalchemy.exc import SQLAlchemyError

from app.aws.mocks import (
    ses_complaint_callback,
    ses_complaint_callback_malformed_message_id,
    ses_complaint_callback_with_missing_complaint_type,
    ses_complaint_callback_with_subtype,
    ses_hard_bounce_callback,
    ses_soft_bounce_callback,
)
from app.dao.notifications_dao import get_notification_by_id
from app.models import (
    NOTIFICATION_HARD_BOUNCE,
    NOTIFICATION_HARD_GENERAL,
    NOTIFICATION_HARD_NOEMAIL,
    NOTIFICATION_HARD_ONACCOUNTSUPPRESSIONLIST,
    NOTIFICATION_HARD_SUPPRESSED,
    NOTIFICATION_SOFT_ATTACHMENTREJECTED,
    NOTIFICATION_SOFT_BOUNCE,
    NOTIFICATION_SOFT_CONTENTREJECTED,
    NOTIFICATION_SOFT_GENERAL,
    NOTIFICATION_SOFT_MAILBOXFULL,
    NOTIFICATION_SOFT_MESSAGETOOLARGE,
    Complaint,
)
from app.notifications.notifications_ses_callback import (
    get_aws_responses,
    handle_complaint,
)
from tests.app.conftest import create_sample_notification
from tests.app.db import (
    create_notification,
    create_notification_history,
    save_notification,
)


@pytest.mark.parametrize(
    "notification_type, bounce_message, expected",
    [
        (
            "Delivery",
            {},
            {
                "message": "Delivered",
                "success": True,
                "notification_status": "delivered",
                "provider_response": None,
                "bounce_response": mock.ANY,
            },
        ),
        (
            "Complaint",
            {},
            {
                "message": "Complaint",
                "success": True,
                "notification_status": "delivered",
                "provider_response": None,
                "bounce_response": mock.ANY,
            },
        ),
        (
            "Bounce",
            {
                "bounceType": "Permanent",
                "bounceSubType": "NoEmail",
                "feedbackId": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                "timestamp": "2017-11-17T12:14:05.131Z",
            },
            {
                "message": "Hard bounced",
                "success": False,
                "notification_status": "permanent-failure",
                "provider_response": None,
                "bounce_response": mock.ANY,
            },
        ),
        (
            "Bounce",
            {
                "bounceType": "Permanent",
                "bounceSubType": "Suppressed",
                "feedbackId": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                "timestamp": "2017-11-17T12:14:05.131Z",
            },
            {
                "message": "Hard bounced",
                "success": False,
                "notification_status": "permanent-failure",
                "provider_response": "The email address is on our email provider suppression list",
                "bounce_response": mock.ANY,
            },
        ),
        (
            "Bounce",
            {
                "bounceType": "Permanent",
                "bounceSubType": "OnAccountSuppressionList",
                "feedbackId": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                "timestamp": "2017-11-17T12:14:05.131Z",
            },
            {
                "message": "Hard bounced",
                "success": False,
                "notification_status": "permanent-failure",
                "provider_response": "The email address is on the GC Notify suppression list",
                "bounce_response": mock.ANY,
            },
        ),
        (
            "Bounce",
            {
                "bounceType": "Transient",
                "bounceSubType": "AttachmentRejected",
                "feedbackId": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                "timestamp": "2017-11-17T12:14:05.131Z",
            },
            {
                "message": "Soft bounced",
                "success": False,
                "notification_status": "temporary-failure",
                "provider_response": "The email was rejected because of its attachments",
                "bounce_response": mock.ANY,
            },
        ),
        (
            "Bounce",
            {
                "bounceType": "Transient",
                "bounceSubType": "MailboxFull",
                "feedbackId": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                "timestamp": "2017-11-17T12:14:05.131Z",
            },
            {
                "message": "Soft bounced",
                "success": False,
                "notification_status": "temporary-failure",
                "provider_response": None,
                "bounce_response": mock.ANY,
            },
        ),
    ],
)
def test_get_aws_responses(notify_api, notification_type, bounce_message, expected):
    with notify_api.test_request_context():
        assert (
            get_aws_responses(
                {
                    "notificationType": notification_type,
                    "bounce": {"bouncedRecipients": "fake"} | bounce_message,
                    "mail": {"destination": "fake"},
                }
            )
            == expected
        )


def test_get_aws_responses_should_be_none_if_unrecognised_status_code(notify_api):
    with notify_api.test_request_context():
        with pytest.raises(KeyError) as e:
            get_aws_responses({"notificationType": "99"})
        assert "99" in str(e.value)


def test_ses_callback_should_not_set_status_once_status_is_delivered(
    client, notify_db, notify_db_session, sample_email_template, mocker
):
    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference="ref",
        status="delivered",
        sent_at=datetime.utcnow(),
    )

    assert get_notification_by_id(notification.id).status == "delivered"


def test_process_ses_results_in_complaint(sample_email_template):
    notification = save_notification(create_notification(template=sample_email_template, reference="ref1"))
    handle_complaint(ses_complaint_callback()["Messages"][0], notification)
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_handle_complaint_does_not_raise_exception_if_reference_is_missing(notify_api):
    response = json.loads(ses_complaint_callback_malformed_message_id()["Messages"])
    handle_complaint(response)
    complaints = Complaint.query.all()
    assert len(complaints) == 0


def test_handle_complaint_does_raise_exception_if_notification_not_found(notify_api):
    response = ses_complaint_callback()["Messages"][0]
    with pytest.raises(expected_exception=SQLAlchemyError):
        handle_complaint(response)


def test_process_ses_results_in_complaint_if_notification_history_does_not_exist(
    sample_email_template,
):
    notification = save_notification(create_notification(template=sample_email_template, reference="ref1"))
    handle_complaint(ses_complaint_callback()["Messages"][0])
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_process_ses_results_in_complaint_if_notification_does_not_exist(
    sample_email_template,
):
    notification = create_notification_history(template=sample_email_template, reference="ref1")
    handle_complaint(ses_complaint_callback()["Messages"][0], notification)
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_process_ses_results_in_complaint_save_complaint_with_null_complaint_type(notify_api, sample_email_template):
    notification = save_notification(create_notification(template=sample_email_template, reference="ref1"))
    msg = json.loads(ses_complaint_callback_with_missing_complaint_type()["Messages"])
    handle_complaint(msg)
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id
    assert not complaints[0].complaint_type


def test_account_suppression_list_complaint_updates_notification_status(sample_email_template):
    notification = save_notification(create_notification(template=sample_email_template, reference="ref1"))
    assert get_notification_by_id(notification.id).status == "created"

    handle_complaint(json.loads(ses_complaint_callback_with_subtype("OnAccountSuppressionList")["Messages"]), notification)
    complaints = Complaint.query.all()

    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id
    assert get_notification_by_id(notification.id).status == "permanent-failure"


def test_regular_complaint_does_not_update_notification_status(sample_email_template):
    notification = save_notification(create_notification(template=sample_email_template, reference="ref1"))
    status = get_notification_by_id(notification.id).status

    handle_complaint(json.loads(ses_complaint_callback_with_missing_complaint_type()["Messages"]), notification)
    complaints = Complaint.query.all()

    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id
    assert get_notification_by_id(notification.id).status == status


class TestBounceRates:
    @pytest.mark.parametrize(
        "bounceType, bounceSubType, expected_bounce_classification",
        [
            (
                "Undetermined",
                "Undetermined",
                {
                    "feedback_type": NOTIFICATION_SOFT_BOUNCE,
                    "feedback_subtype": NOTIFICATION_SOFT_GENERAL,
                    "ses_feedback_id": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                    "ses_feedback_date": "2017-11-17T12:14:05.131Z",
                },
            ),
            (
                "Permanent",
                "General",
                {
                    "feedback_type": NOTIFICATION_HARD_BOUNCE,
                    "feedback_subtype": NOTIFICATION_HARD_GENERAL,
                    "ses_feedback_id": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                    "ses_feedback_date": "2017-11-17T12:14:05.131Z",
                },
            ),
            (
                "Permanent",
                "NoEmail",
                {
                    "feedback_type": NOTIFICATION_HARD_BOUNCE,
                    "feedback_subtype": NOTIFICATION_HARD_NOEMAIL,
                    "ses_feedback_id": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                    "ses_feedback_date": "2017-11-17T12:14:05.131Z",
                },
            ),
            (
                "Permanent",
                "Suppressed",
                {
                    "feedback_type": NOTIFICATION_HARD_BOUNCE,
                    "feedback_subtype": NOTIFICATION_HARD_SUPPRESSED,
                    "ses_feedback_id": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                    "ses_feedback_date": "2017-11-17T12:14:05.131Z",
                },
            ),
            (
                "Permanent",
                "OnAccountSuppressionList",
                {
                    "feedback_type": NOTIFICATION_HARD_BOUNCE,
                    "feedback_subtype": NOTIFICATION_HARD_ONACCOUNTSUPPRESSIONLIST,
                    "ses_feedback_id": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                    "ses_feedback_date": "2017-11-17T12:14:05.131Z",
                },
            ),
            (
                "Transient",
                "General",
                {
                    "feedback_type": NOTIFICATION_SOFT_BOUNCE,
                    "feedback_subtype": NOTIFICATION_SOFT_GENERAL,
                    "ses_feedback_id": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                    "ses_feedback_date": "2017-11-17T12:14:05.131Z",
                },
            ),
            (
                "Transient",
                "MailboxFull",
                {
                    "feedback_type": NOTIFICATION_SOFT_BOUNCE,
                    "feedback_subtype": NOTIFICATION_SOFT_MAILBOXFULL,
                    "ses_feedback_id": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                    "ses_feedback_date": "2017-11-17T12:14:05.131Z",
                },
            ),
            (
                "Transient",
                "MessageTooLarge",
                {
                    "feedback_type": NOTIFICATION_SOFT_BOUNCE,
                    "feedback_subtype": NOTIFICATION_SOFT_MESSAGETOOLARGE,
                    "ses_feedback_id": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                    "ses_feedback_date": "2017-11-17T12:14:05.131Z",
                },
            ),
            (
                "Transient",
                "ContentRejected",
                {
                    "feedback_type": NOTIFICATION_SOFT_BOUNCE,
                    "feedback_subtype": NOTIFICATION_SOFT_CONTENTREJECTED,
                    "ses_feedback_id": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                    "ses_feedback_date": "2017-11-17T12:14:05.131Z",
                },
            ),
            (
                "Transient",
                "AttachmentRejected",
                {
                    "feedback_type": NOTIFICATION_SOFT_BOUNCE,
                    "feedback_subtype": NOTIFICATION_SOFT_ATTACHMENTREJECTED,
                    "ses_feedback_id": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
                    "ses_feedback_date": "2017-11-17T12:14:05.131Z",
                },
            ),
        ],
    )
    def test_bounce_types(self, notify_api, bounceType, bounceSubType, expected_bounce_classification):
        if bounceType == "Permanent":
            bounce_message = ses_hard_bounce_callback(reference="ref", bounce_subtype=bounceSubType)["Messages"][0]
        elif bounceType == "Transient" or bounceType == "Undetermined":
            bounce_message = ses_soft_bounce_callback(reference="ref", bounce_subtype=bounceSubType)["Messages"][0]
            if bounceType == "Undetermined":
                bounce_message["bounce"]["bounceType"] = "Undetermined"

        with notify_api.test_request_context():
            # test = get_aws_responses(bounce_message)["bounce_response"]
            assert get_aws_responses(bounce_message)["bounce_response"] == expected_bounce_classification
