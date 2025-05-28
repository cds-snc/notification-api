from flask import current_app, json

from app.celery.service_callback_tasks import send_complaint_to_service
from app.config import QueueNames
from app.dao.complaint_dao import save_complaint
from app.dao.notifications_dao import (
    _update_notification_status,
    dao_get_notification_history_by_reference,
)
from app.dao.service_callback_api_dao import (
    get_service_complaint_callback_api_for_service,
)
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
    NOTIFICATION_UNKNOWN_BOUNCE_SUBTYPE,
    Complaint,
)
from app.notifications.callbacks import create_complaint_callback_data


def _determine_notification_bounce_type(ses_message):
    notification_type = ses_message["notificationType"]
    if notification_type in ["Delivery", "Complaint"]:
        return notification_type

    if notification_type != "Bounce":
        raise KeyError(f"Unhandled notification type {notification_type}")

    remove_emails_from_bounce(ses_message)
    current_app.logger.info("SES bounce dict: {}".format(json.dumps(ses_message).replace("{", "(").replace("}", ")")))
    if ses_message["bounce"]["bounceType"] == "Permanent":
        return "Permanent"
    return "Temporary"


def _determine_provider_response(ses_message):
    if ses_message["notificationType"] != "Bounce":
        return None

    bounce_type = ses_message["bounce"]["bounceType"]
    bounce_subtype = ses_message["bounce"]["bounceSubType"]

    # See https://docs.aws.amazon.com/ses/latest/DeveloperGuide/event-publishing-retrieving-sns-contents.html
    if bounce_type == "Permanent" and bounce_subtype == "Suppressed":
        return "The email address is on our email provider suppression list"
    elif bounce_type == "Permanent" and bounce_subtype == "OnAccountSuppressionList":
        return "The email address is on the GC Notify suppression list"
    elif bounce_type == "Transient" and bounce_subtype == "AttachmentRejected":
        return "The email was rejected because of its attachments"

    return None


def _determine_bounce_response(ses_message):
    if ses_message["notificationType"] != "Bounce":
        return None

    bounce_type = ses_message["bounce"].get("bounceType")
    bounce_subtype = ses_message["bounce"].get("bounceSubType")

    bounce_response = {
        "feedback_type": NOTIFICATION_UNKNOWN_BOUNCE,  # default to unknown bounce
        "feedback_subtype": NOTIFICATION_UNKNOWN_BOUNCE_SUBTYPE,  # default to unknown bounce subtype
        "ses_feedback_id": ses_message["bounce"].get("feedbackId"),
        "ses_feedback_date": ses_message["bounce"].get("timestamp"),
    }

    # See https://docs.aws.amazon.com/ses/latest/dg/notification-contents.html#bounce-types for all bounce types
    if bounce_type == "Undetermined":  # treat this as a soft bounce since we don't know what went wrong
        bounce_response["feedback_type"] = NOTIFICATION_SOFT_BOUNCE
        bounce_response["feedback_subtype"] = NOTIFICATION_SOFT_GENERAL
    elif bounce_type == "Permanent":
        bounce_response["feedback_type"] = NOTIFICATION_HARD_BOUNCE
        if bounce_subtype == "General":
            bounce_response["feedback_subtype"] = NOTIFICATION_HARD_GENERAL
        if bounce_subtype == "NoEmail":
            bounce_response["feedback_subtype"] = NOTIFICATION_HARD_NOEMAIL
        if bounce_subtype == "Suppressed":
            bounce_response["feedback_subtype"] = NOTIFICATION_HARD_SUPPRESSED
        if bounce_subtype == "OnAccountSuppressionList":
            bounce_response["feedback_subtype"] = NOTIFICATION_HARD_ONACCOUNTSUPPRESSIONLIST
    elif bounce_type == "Transient":
        bounce_response["feedback_type"] = NOTIFICATION_SOFT_BOUNCE
        if bounce_subtype == "General":
            bounce_response["feedback_subtype"] = NOTIFICATION_SOFT_GENERAL
        if bounce_subtype == "MailboxFull":
            bounce_response["feedback_subtype"] = NOTIFICATION_SOFT_MAILBOXFULL
        if bounce_subtype == "MessageTooLarge":
            bounce_response["feedback_subtype"] = NOTIFICATION_SOFT_MESSAGETOOLARGE
        if bounce_subtype == "ContentRejected":
            bounce_response["feedback_subtype"] = NOTIFICATION_SOFT_CONTENTREJECTED
        if bounce_subtype == "AttachmentRejected":
            bounce_response["feedback_subtype"] = NOTIFICATION_SOFT_ATTACHMENTREJECTED
    else:
        current_app.logger.info(
            "Unknown bounce type received. SES bounce dict: {}".format(
                json.dumps(ses_message).replace("{", "(").replace("}", ")")
            )
        )
    return bounce_response


def get_aws_responses(ses_message):
    status = _determine_notification_bounce_type(ses_message)

    base = {
        "Permanent": {
            "message": "Hard bounced",
            "success": False,
            "notification_status": "permanent-failure",
        },
        "Temporary": {
            "message": "Soft bounced",
            "success": False,
            "notification_status": "temporary-failure",
        },
        "Delivery": {
            "message": "Delivered",
            "success": True,
            "notification_status": "delivered",
        },
        "Complaint": {
            "message": "Complaint",
            "success": True,
            "notification_status": "delivered",
        },
    }[status]

    base["provider_response"] = _determine_provider_response(ses_message)
    base["bounce_response"] = _determine_bounce_response(ses_message)
    return base


def handle_complaint(ses_message):
    recipient_emails = remove_emails_from_complaint(ses_message)
    recipient_email = recipient_emails[0] if recipient_emails else None
    current_app.logger.info("Complaint from SES: \n{}".format(json.dumps(ses_message).replace("{", "(").replace("}", ")")))
    try:
        reference = ses_message["mail"]["messageId"]
    except KeyError:
        current_app.logger.exception("Complaint from SES failed to get reference from message")
        return
    notification = dao_get_notification_history_by_reference(reference)
    ses_complaint = ses_message.get("complaint", None)

    complaint = Complaint(
        notification_id=notification.id,
        service_id=notification.service_id,
        ses_feedback_id=ses_complaint.get("feedbackId", None) if ses_complaint else None,
        complaint_type=ses_complaint.get("complaintFeedbackType", None) if ses_complaint else None,
        complaint_date=ses_complaint.get("timestamp", None) if ses_complaint else None,
    )
    save_complaint(complaint)

    # if the subtype is onaccountsuppressionlist, update the original notification to be permanent failure
    if ses_complaint:
        feedback_subtype = ses_complaint.get("complaintSubType", None)

        if feedback_subtype == "OnAccountSuppressionList":
            current_app.logger.info(
                "Complaint of sub-type 'OnAccountSuppressionList' received;  updating notification id {} to permanent-failure".format(
                    notification.id
                )
            )
            _update_notification_status(
                notification=notification,
                status=NOTIFICATION_PERMANENT_FAILURE,
                provider_response="The email address is on the GC Notify suppression list",  # TODO: move provider_responses to constants
            )

    return complaint, notification, recipient_email


def remove_mail_headers(dict_to_edit):
    if dict_to_edit["mail"].get("headers"):
        dict_to_edit["mail"].pop("headers")
    if dict_to_edit["mail"].get("commonHeaders"):
        dict_to_edit["mail"].pop("commonHeaders")


def remove_emails_from_bounce(bounce_dict):
    remove_mail_headers(bounce_dict)
    bounce_dict["mail"].pop("destination")
    bounce_dict["bounce"].pop("bouncedRecipients")


def remove_emails_from_complaint(complaint_dict):
    remove_mail_headers(complaint_dict)
    # If the complaint is because the email address is on the suppression list, there will be no
    # complainedRecipients in the SES message from which we can get the email address.
    if complaint_dict["complaint"].get("complaintSubType") == "OnAccountSuppressionList":
        return None
    complaint_dict["complaint"].pop("complainedRecipients")
    return complaint_dict["mail"].pop("destination")


def _check_and_queue_complaint_callback_task(complaint, notification, recipient):
    # queue callback task only if the service_callback_api exists
    service_callback_api = get_service_complaint_callback_api_for_service(service_id=notification.service_id)
    if service_callback_api:
        complaint_data = create_complaint_callback_data(complaint, notification, service_callback_api, recipient)
        send_complaint_to_service.apply_async([complaint_data, notification.service_id], queue=QueueNames.CALLBACKS)
