import pytest
from flask import json
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from uuid import uuid4

from app.dao.notifications_dao import get_notification_by_id
from app.models import Complaint, EMAIL_TYPE, NotificationHistory, UNKNOWN_COMPLAINT_TYPE
from app.notifications.notifications_ses_callback import handle_ses_complaint, handle_smtp_complaint

from tests.app.db import (
    ses_complaint_callback_malformed_message_id,
    ses_complaint_callback_with_missing_complaint_type,
    ses_complaint_callback,
    create_notification_history,
)


def test_ses_callback_should_not_set_status_once_status_is_delivered(
    sample_notification,
):
    notification = sample_notification(gen_type=EMAIL_TYPE)
    notification.status = 'delivered'

    assert get_notification_by_id(notification.id).status == 'delivered'


def test_process_ses_results_in_complaint(
    notify_db_session,
    sample_notification,
):
    ref = str(uuid4())
    notification = sample_notification(gen_type=EMAIL_TYPE, reference=ref)
    complaint = ses_complaint_callback()['Message'].replace('ref1', ref)
    handle_ses_complaint(json.loads(complaint))

    stmt = select(Complaint).where(Complaint.service_id == notification.service.id)
    complaints = notify_db_session.session.scalars(stmt).all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_handle_complaint_does_not_raise_exception_if_reference_is_missing():
    response = json.loads(ses_complaint_callback_malformed_message_id()['Message'])
    assert handle_ses_complaint(response) is None


def test_handle_complaint_does_raise_exception_if_notification_not_found():
    response = json.loads(ses_complaint_callback()['Message'])
    with pytest.raises(expected_exception=SQLAlchemyError):
        handle_ses_complaint(response)


def test_process_ses_results_in_complaint_if_notification_history_does_not_exist(
    notify_db_session,
    sample_notification,
):
    ref = str(uuid4())
    notification = sample_notification(gen_type=EMAIL_TYPE, reference=ref)
    complaint = ses_complaint_callback()['Message'].replace('ref1', ref)
    handle_ses_complaint(json.loads(complaint))

    stmt = select(Complaint).where(Complaint.service_id == notification.service.id)
    complaints = notify_db_session.session.scalars(stmt).all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_process_ses_results_in_complaint_if_notification_does_not_exist(
    notify_db_session,
    sample_template,
):
    ref = str(uuid4())
    notification = create_notification_history(template=sample_template(template_type=EMAIL_TYPE), reference=ref)
    complaint = ses_complaint_callback()['Message'].replace('ref1', ref)
    handle_ses_complaint(json.loads(complaint))

    stmt = select(Complaint).where(Complaint.service_id == notification.service.id)
    complaints = notify_db_session.session.scalars(stmt).all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id

    # Teardown
    notification_to_delete = notify_db_session.session.get(NotificationHistory, notification.id)
    notify_db_session.session.delete(notification_to_delete)
    notify_db_session.session.commit()


def test_process_ses_results_in_complaint_save_complaint_with_null_complaint_type(
    notify_db_session,
    sample_notification,
):
    ref = str(uuid4())
    notification = sample_notification(gen_type=EMAIL_TYPE, reference=ref)
    complaint = ses_complaint_callback_with_missing_complaint_type()['Message'].replace('ref1', ref)
    handle_ses_complaint(json.loads(complaint))

    stmt = select(Complaint).where(Complaint.service_id == notification.service.id)
    complaints = notify_db_session.session.scalars(stmt).all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id
    assert complaints[0].complaint_type == UNKNOWN_COMPLAINT_TYPE


def test_process_ses_smtp_results_in_complaint(
    notify_db_session,
    sample_notification,
):
    ref = str(uuid4())
    notification = sample_notification(gen_type=EMAIL_TYPE, reference=ref)
    complaint = ses_complaint_callback()['Message'].replace('ref1', ref)
    handle_smtp_complaint(json.loads(complaint))

    stmt = select(Complaint).where(Complaint.service_id == notification.service.id)
    complaints = notify_db_session.session.scalars(stmt).all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_handle_smtp_complaint_does_not_raise_exception_if_reference_is_missing(notify_api):
    response = json.loads(ses_complaint_callback_malformed_message_id()['Message'])
    assert handle_smtp_complaint(response) is None


def test_handle_smtp_complaint_does_raise_exception_if_notification_not_found(
    notify_api,
):
    ref = str(uuid4())
    complaint = ses_complaint_callback()['Message'].replace('ref1', ref)
    response = json.loads(complaint)
    with pytest.raises(expected_exception=SQLAlchemyError):
        handle_smtp_complaint(response)


def test_process_ses_smtp_results_in_complaint_if_notification_history_does_not_exist(
    notify_db_session,
    sample_notification,
):
    ref = str(uuid4())
    notification = sample_notification(gen_type=EMAIL_TYPE, reference=ref)
    complaint = ses_complaint_callback()['Message'].replace('ref1', ref)
    handle_smtp_complaint(json.loads(complaint))

    stmt = select(Complaint).where(Complaint.service_id == notification.service.id)
    complaints = notify_db_session.session.scalars(stmt).all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id


def test_process_ses_smtp_results_in_complaint_if_notification_does_not_exist(
    notify_db_session,
    sample_template,
):
    ref = str(uuid4())
    complaint = ses_complaint_callback()['Message'].replace('ref1', ref)
    notification = create_notification_history(template=sample_template(template_type=EMAIL_TYPE), reference=ref)
    handle_smtp_complaint(json.loads(complaint))

    stmt = select(Complaint).where(Complaint.service_id == notification.service.id)
    complaints = notify_db_session.session.scalars(stmt).all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id

    # Teardown
    notification_to_delete = notify_db_session.session.get(NotificationHistory, notification.id)
    notify_db_session.session.delete(notification_to_delete)
    notify_db_session.session.commit()


def test_process_smtp_results_in_complaint_save_complaint_with_null_complaint_type(
    notify_db_session,
    sample_notification,
):
    ref = str(uuid4())
    notification = sample_notification(gen_type=EMAIL_TYPE, reference=ref)
    complaint = ses_complaint_callback_with_missing_complaint_type()['Message'].replace('ref1', ref)
    handle_smtp_complaint(json.loads(complaint))

    stmt = select(Complaint).where(Complaint.service_id == notification.service.id)
    complaints = notify_db_session.session.scalars(stmt).all()
    assert len(complaints) == 1
    assert complaints[0].notification_id == notification.id
    assert complaints[0].complaint_type == UNKNOWN_COMPLAINT_TYPE
