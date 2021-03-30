from typing import Tuple

from flask import (
    current_app,
    json
)

from app.dao.complaint_dao import save_complaint
from app.dao.notifications_dao import dao_get_notification_history_by_reference
from app.models import Complaint, Notification


def determine_notification_bounce_type(notification_type, ses_message):
    remove_emails_from_bounce(ses_message)
    current_app.logger.info('SES bounce dict: {}'.format(json.dumps(ses_message).replace('{', '(').replace('}', ')')))
    return 'Permanent' if ses_message['bounce']['bounceType'] == 'Permanent' else 'Temporary'


def handle_ses_complaint(ses_message: dict) -> Tuple[Complaint, Notification, str]:
    recipient_email = remove_emails_from_complaint(ses_message)[0]
    current_app.logger.info(
        "Complaint from SES: \n{}".format(json.dumps(ses_message).replace('{', '(').replace('}', ')')))
    try:
        reference = ses_message['mail']['messageId']
    except KeyError as e:
        current_app.logger.exception("Complaint from SES failed to get reference from message", e)
        return
    notification = dao_get_notification_history_by_reference(reference)
    ses_complaint = ses_message.get('complaint', None)

    complaint = Complaint(
        notification_id=notification.id,
        service_id=notification.service_id,
        ses_feedback_id=ses_complaint.get('feedbackId', None) if ses_complaint else None,
        complaint_type=ses_complaint.get('complaintFeedbackType', None) if ses_complaint else None,
        complaint_date=ses_complaint.get('timestamp', None) if ses_complaint else None
    )
    save_complaint(complaint)
    return complaint, notification, recipient_email


def handle_smtp_complaint(ses_message):
    recipient_email = remove_emails_from_complaint(ses_message)[0]
    current_app.logger.info(
        "Complaint from SES SMTP: \n{}".format(json.dumps(ses_message).replace('{', '(').replace('}', ')')))
    try:
        reference = ses_message['mail']['messageId']
    except KeyError as e:
        current_app.logger.exception("Complaint from SES SMTP failed to get reference from message", e)
        return
    notification = dao_get_notification_history_by_reference(reference)
    ses_complaint = ses_message.get('complaint', None)

    complaint = Complaint(
        notification_id=notification.id,
        service_id=notification.service_id,
        ses_feedback_id=ses_complaint.get('feedbackId', None) if ses_complaint else None,
        complaint_type=ses_complaint.get('complaintFeedbackType', None) if ses_complaint else None,
        complaint_date=ses_complaint.get('timestamp', None) if ses_complaint else None
    )
    save_complaint(complaint)
    return complaint, notification, recipient_email


def remove_mail_headers(dict_to_edit):
    if dict_to_edit['mail'].get('headers'):
        dict_to_edit['mail'].pop('headers')
    if dict_to_edit['mail'].get('commonHeaders'):
        dict_to_edit['mail'].pop('commonHeaders')


def remove_emails_from_bounce(bounce_dict):
    remove_mail_headers(bounce_dict)
    bounce_dict['mail'].pop('destination')
    bounce_dict['bounce'].pop('bouncedRecipients')


def remove_emails_from_complaint(complaint_dict):
    remove_mail_headers(complaint_dict)
    complaint_dict['complaint'].pop('complainedRecipients')
    return complaint_dict['mail'].pop('destination')
