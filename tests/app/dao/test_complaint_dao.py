from datetime import datetime, timedelta
from uuid import uuid4


from app.dao.complaint_dao import (
    fetch_complaints_by_service,
    save_complaint,
    fetch_complaint_by_id,
)
from app.constants import EMAIL_TYPE
from app.models import Complaint


def test_fetch_complaint_by_service_returns_one(sample_service, sample_template, sample_notification):
    service = sample_service()
    template = sample_template(template_type=EMAIL_TYPE, service=service)
    notification = sample_notification(template=template)
    complaint = Complaint(
        notification_id=notification.id,
        service_id=service.id,
        feedback_id=str(uuid4()),
        complaint_type='abuse',
        complaint_date=datetime.utcnow(),
    )

    save_complaint(complaint)

    complaints = fetch_complaints_by_service(service_id=service.id)
    assert len(complaints) == 1
    assert complaints[0] == complaint


def test_fetch_complaint_by_service_returns_empty_list(sample_service):
    complaints = fetch_complaints_by_service(service_id=sample_service().id)
    assert len(complaints) == 0


def test_fetch_complaint_by_service_return_many(sample_service, sample_template, sample_notification):
    service_1 = sample_service(service_name='first')
    service_2 = sample_service(service_name='second')
    template_1 = sample_template(service=service_1, template_type=EMAIL_TYPE)
    template_2 = sample_template(service=service_2, template_type=EMAIL_TYPE)
    notification_1 = sample_notification(template=template_1)
    notification_2 = sample_notification(template=template_2)
    notification_3 = sample_notification(template=template_2)
    complaint_1 = Complaint(
        notification_id=notification_1.id,
        service_id=service_1.id,
        feedback_id=str(uuid4()),
        complaint_type='abuse',
        complaint_date=datetime.utcnow(),
    )
    complaint_2 = Complaint(
        notification_id=notification_2.id,
        service_id=service_2.id,
        feedback_id=str(uuid4()),
        complaint_type='abuse',
        complaint_date=datetime.utcnow(),
    )
    complaint_3 = Complaint(
        notification_id=notification_3.id,
        service_id=service_2.id,
        feedback_id=str(uuid4()),
        complaint_type='abuse',
        complaint_date=datetime.utcnow(),
        created_at=datetime.utcnow() + timedelta(minutes=1),
    )

    save_complaint(complaint_1)
    save_complaint(complaint_2)
    save_complaint(complaint_3)

    complaints = fetch_complaints_by_service(service_id=service_2.id)
    assert len(complaints) == 2
    assert complaints[0] == complaint_3
    assert complaints[1] == complaint_2


def test_fetch_complaint_by_id(sample_complaint, sample_template, sample_notification):
    template = sample_template(template_type=EMAIL_TYPE)
    notification = sample_notification(template=template)

    complaint = sample_complaint(
        service=notification.service, notification=notification, created_at=datetime(2018, 1, 1)
    )

    complaints_from_db = fetch_complaint_by_id(complaint.id).all()

    assert complaints_from_db[0].id == complaint.id


def test_fetch_complaint_by_id_does_not_return_anything(sample_template, sample_notification):
    template = sample_template(template_type=EMAIL_TYPE)
    sample_notification(template=template)

    complaints_from_db = fetch_complaint_by_id(uuid4()).all()

    assert len(complaints_from_db) == 0
