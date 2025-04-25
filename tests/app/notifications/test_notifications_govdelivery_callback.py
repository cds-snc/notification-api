import uuid

from dateutil import parser

from app.models import Notification, Complaint
from app.notifications.notifications_govdelivery_callback import create_complaint


def get_govdelivery_request(reference, status, error_message=None):
    return {
        'sid': 'some_sid',
        'message_url': 'https://tms.govdelivery.com/messages/sms/{0}'.format(reference),
        'recipient_url': 'https://tms.govdelivery.com/messages/sms/{0}/recipients/373810'.format(reference),
        'status': status,
        'message_type': 'sms',
        'completed_at': '2015-08-05 18:47:18 UTC',
        'error_message': error_message,
    }


def test_create_complaint_should_return_complaint_with_correct_info(mocker, notify_api):
    request = get_govdelivery_request('1111', 'blacklisted')

    test_email = 'some_email@gov.gov'

    mocker.patch('app.notifications.notifications_govdelivery_callback.save_complaint')

    test_notification = Notification(id=uuid.uuid4(), to=test_email, service_id=uuid.uuid4())

    expected_complaint = Complaint(
        notification_id=test_notification.id,
        service_id=test_notification.service_id,
        feedback_id=request['sid'],
        complaint_type=request['message_type'],
        complaint_date=parser.parse(request['completed_at']),
    )

    with notify_api.app_context():
        complaint = create_complaint(request, test_notification)

        assert_complaints_are_equal(expected_complaint, complaint)


def assert_complaints_are_equal(expected_complaint, actual_complaint):
    assert expected_complaint.notification_id == actual_complaint.notification_id
    assert expected_complaint.service_id == actual_complaint.service_id
    assert expected_complaint.feedback_id == actual_complaint.feedback_id
    assert expected_complaint.complaint_type == actual_complaint.complaint_type
    assert expected_complaint.complaint_date == actual_complaint.complaint_date
