from flask import (
    current_app,
    json
)

from app.dao.complaint_dao import save_complaint
from app.dao.notifications_dao import dao_get_notification_history_by_reference
from app.models import Complaint
from app.dao.service_callback_api_dao import (
    get_service_complaint_callback_api_for_service,
)
from app.notifications.callbacks import create_complaint_callback_data
from app.celery.service_callback_tasks import (
    send_complaint_to_service,
)
from app.config import QueueNames


def _determine_notification_bounce_type(ses_message):
    notification_type = ses_message['notificationType']
    if notification_type in ['Delivery', 'Complaint']:
        return notification_type

    if notification_type != 'Bounce':
        raise KeyError(f"Unhandled notification type {notification_type}")

    remove_emails_from_bounce(ses_message)
    current_app.logger.info('SES bounce dict: {}'.format(json.dumps(ses_message).replace('{', '(').replace('}', ')')))
    if ses_message['bounce']['bounceType'] == 'Permanent':
        return 'Permanent'
    return 'Temporary'


def _determine_provider_response(ses_message):
    if ses_message['notificationType'] != 'Bounce':
        return None

    bounce_type = ses_message['bounce']['bounceType']
    bounce_subtype = ses_message['bounce']['bounceSubType']

    # See https://docs.aws.amazon.com/ses/latest/DeveloperGuide/event-publishing-retrieving-sns-contents.html
    if bounce_type == 'Permanent' and bounce_subtype == 'Suppressed':
        return 'Email address is on the Amazon suppression list'
    elif bounce_type == 'Permanent' and bounce_subtype == 'OnAccountSuppressionList':
        return 'Email address is on the GC Notify suppression list'
    elif bounce_type == 'Transient' and bounce_subtype == 'AttachmentRejected':
        return 'Email was rejected because of its attachments'

    return None


def get_aws_responses(ses_message):
    status = _determine_notification_bounce_type(ses_message)

    base = {
        'Permanent': {
            "message": 'Hard bounced',
            "success": False,
            "notification_status": 'permanent-failure',
        },
        'Temporary': {
            "message": 'Soft bounced',
            "success": False,
            "notification_status": 'temporary-failure',
        },
        'Delivery': {
            "message": 'Delivered',
            "success": True,
            "notification_status": 'delivered',
        },
        'Complaint': {
            "message": 'Complaint',
            "success": True,
            "notification_status": 'delivered',
        }
    }[status]

    base['provider_response'] = _determine_provider_response(ses_message)

    return base


def handle_complaint(ses_message):
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


def _check_and_queue_complaint_callback_task(complaint, notification, recipient):
    # queue callback task only if the service_callback_api exists
    service_callback_api = get_service_complaint_callback_api_for_service(service_id=notification.service_id)
    if service_callback_api:
        complaint_data = create_complaint_callback_data(complaint, notification, service_callback_api, recipient)
        send_complaint_to_service.apply_async([complaint_data], queue=QueueNames.CALLBACKS)
