from datetime import datetime

import pytest
from flask import json
from sqlalchemy.exc import SQLAlchemyError

from app.dao.notifications_dao import get_notification_by_id
from app.models import Complaint
from app.notifications.notifications_ses_callback import (
    get_aws_responses,
    handle_complaint,
    handle_smtp_complaint,
)

from tests.app.conftest import sample_notification as create_sample_notification
from tests.app.db import (
    create_notification, ses_complaint_callback_malformed_message_id,
    ses_complaint_callback_with_missing_complaint_type,
    ses_complaint_callback,
    create_notification_history
)


@pytest.mark.parametrize('notification_type, bounce_message, expected', [
    (
        'Delivery',
        {},
        {
            'message': 'Delivered',
            'success': True,
            'notification_status': 'delivered',
            'provider_response': None,
        }
    ),
    (
        'Complaint',
        {},
        {
            'message': 'Complaint',
            'success': True,
            'notification_status': 'delivered',
            'provider_response': None,
        }
    ),
    (
        'Bounce',
        {'bounceType': 'Permanent', 'bounceSubType': 'NoEmail'},
        {
            'message': 'Hard bounced',
            'success': False,
            'notification_status': 'permanent-failure',
            'provider_response': None,
        }
    ),
    (
        'Bounce',
        {'bounceType': 'Permanent', 'bounceSubType': 'Suppressed'},
        {
            'message': 'Hard bounced',
            'success': False,
            'notification_status': 'permanent-failure',
            'provider_response': 'The email address is on our email provider suppression list',
        }
    ),
    (
        'Bounce',
        {'bounceType': 'Permanent', 'bounceSubType': 'OnAccountSuppressionList'},
        {
            'message': 'Hard bounced',
            'success': False,
            'notification_status': 'permanent-failure',
            'provider_response': 'The email address is on the GC Notify suppression list',
        }
    ),
    (
        'Bounce',
        {'bounceType': 'Transient', 'bounceSubType': 'AttachmentRejected'},
        {
            'message': 'Soft bounced',
            'success': False,
            'notification_status': 'temporary-failure',
            'provider_response': 'The email was rejected because of its attachments',
        }
    ),
    (
        'Bounce',
        {'bounceType': 'Transient', 'bounceSubType': 'MailboxFull'},
        {
            'message': 'Soft bounced',
            'success': False,
            'notification_status': 'temporary-failure',
            'provider_response': None,
        }
    ),
])
def test_get_aws_responses(notify_api, notification_type, bounce_message, expected):
    with notify_api.test_request_context():
        assert get_aws_responses(
            {
                'notificationType': notification_type,
                'bounce': {'bouncedRecipients': 'fake'} | bounce_message,
                'mail': {'destination': "fake"},
            }
        ) == expected


def test_get_aws_responses_should_be_none_if_unrecognised_status_code(notify_api):
    with notify_api.test_request_context():
        with pytest.raises(KeyError) as e:
            get_aws_responses({'notificationType': '99'})
        assert '99' in str(e.value)


def test_ses_callback_should_not_set_status_once_status_is_delivered(client,
                                                                     notify_db,
                                                                     notify_db_session,
                                                                     sample_email_template,
                                                                     mocker):
    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        template=sample_email_template,
        reference='ref',
        status='delivered',
        sent_at=datetime.utcnow()
    )

    assert get_notification_by_id(notification.id).status == 'delivered'


def test_process_ses_results_in_complaint(sample_email_template):
    notification = create_notification(template=sample_email_template, reference='ref1')
    handle_complaint(json.loads(ses_complaint_callback()['Message']))
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_handle_complaint_does_not_raise_exception_if_reference_is_missing(notify_api):
    response = json.loads(ses_complaint_callback_malformed_message_id()['Message'])
    handle_complaint(response)
    assert len(Complaint.query.all()) == 0


def test_handle_complaint_does_raise_exception_if_notification_not_found(notify_api):
    response = json.loads(ses_complaint_callback()['Message'])
    with pytest.raises(expected_exception=SQLAlchemyError):
        handle_complaint(response)


def test_process_ses_results_in_complaint_if_notification_history_does_not_exist(sample_email_template):
    notification = create_notification(template=sample_email_template, reference='ref1')
    handle_complaint(json.loads(ses_complaint_callback()['Message']))
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_process_ses_results_in_complaint_if_notification_does_not_exist(sample_email_template):
    notification = create_notification_history(template=sample_email_template, reference='ref1')
    handle_complaint(json.loads(ses_complaint_callback()['Message']))
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_process_ses_results_in_complaint_save_complaint_with_null_complaint_type(notify_api, sample_email_template):
    notification = create_notification(template=sample_email_template, reference='ref1')
    msg = json.loads(ses_complaint_callback_with_missing_complaint_type()['Message'])
    handle_complaint(msg)
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id
    assert not complaints[0].complaint_type


def test_process_ses_smtp_results_in_complaint(sample_email_template):
    notification = create_notification(template=sample_email_template, reference='ref1')
    handle_smtp_complaint(json.loads(ses_complaint_callback()['Message']))
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_handle_smtp_complaint_does_not_raise_exception_if_reference_is_missing(notify_api):
    response = json.loads(ses_complaint_callback_malformed_message_id()['Message'])
    handle_smtp_complaint(response)
    assert len(Complaint.query.all()) == 0


def test_handle_smtp_complaint_does_raise_exception_if_notification_not_found(notify_api):
    response = json.loads(ses_complaint_callback()['Message'])
    with pytest.raises(expected_exception=SQLAlchemyError):
        handle_smtp_complaint(response)


def test_process_ses_smtp_results_in_complaint_if_notification_history_does_not_exist(sample_email_template):
    notification = create_notification(template=sample_email_template, reference='ref1')
    handle_smtp_complaint(json.loads(ses_complaint_callback()['Message']))
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_process_ses_smtp_results_in_complaint_if_notification_does_not_exist(sample_email_template):
    notification = create_notification_history(template=sample_email_template, reference='ref1')
    handle_smtp_complaint(json.loads(ses_complaint_callback()['Message']))
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_process_smtp_results_in_complaint_save_complaint_with_null_complaint_type(notify_api, sample_email_template):
    notification = create_notification(template=sample_email_template, reference='ref1')
    msg = json.loads(ses_complaint_callback_with_missing_complaint_type()['Message'])
    handle_smtp_complaint(msg)
    complaints = Complaint.query.all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id
    assert not complaints[0].complaint_type
