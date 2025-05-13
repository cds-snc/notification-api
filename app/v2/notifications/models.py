from flask_restx import fields

from app.v2.openapi import api

# Common fields that can be reused
template_id_field = fields.String(required=True, description="The ID of the template")
email_field = fields.String(required=True, description="The email address of the recipient")
phone_number_field = fields.String(required=True, description="The phone number of the recipient")
reference_field = fields.String(description="A reference that identifies the notification")
personalisation_field = fields.Raw(description="The template variables")
schedule_for_field = fields.DateTime(description="The time to send the notification")
reply_to_id_field = fields.String(description="The ID of the reply-to address or phone number")

# Base Models
template_ref = api.model(
    "TemplateRef",
    {
        "id": fields.String(required=True, description="Template ID"),
        "version": fields.Integer(required=True, description="Template version"),
        "uri": fields.String(required=True, description="Template URI"),
    },
)

notification_response_base = api.model(
    "NotificationResponseBase",
    {
        "id": fields.String(required=True, description="Notification ID"),
        "reference": fields.String(description="Client reference"),
        "uri": fields.String(required=True, description="Notification URI"),
        "template": fields.Nested(template_ref),
        "scheduled_for": fields.DateTime(description="When the notification is scheduled to be sent"),
    },
)

# Request models
sms_request = api.model(
    "SmsRequest",
    {
        "template_id": template_id_field,
        "phone_number": phone_number_field,
        "reference": reference_field,
        "personalisation": personalisation_field,
        "scheduled_for": schedule_for_field,
        "sms_sender_id": reply_to_id_field,
    },
)

email_request = api.model(
    "EmailRequest",
    {
        "template_id": template_id_field,
        "email_address": email_field,
        "reference": reference_field,
        "personalisation": personalisation_field,
        "scheduled_for": schedule_for_field,
        "email_reply_to_id": reply_to_id_field,
    },
)

bulk_row = api.model(
    "BulkRow",
    {
        "phone_number": fields.String(description="The phone number for SMS notifications"),
        "email_address": fields.String(description="The email address for email notifications"),
        "personalisation": personalisation_field,
    },
)

bulk_request = api.model(
    "BulkRequest",
    {
        "template_id": template_id_field,
        "rows": fields.List(fields.List(fields.String), description="The data for each notification"),
        "csv": fields.String(description="The CSV data for the notifications"),
        "name": fields.String(description="The name of the file"),
        "scheduled_for": schedule_for_field,
        "reply_to_id": reply_to_id_field,
    },
)

# Response models
sms_response = api.inherit(
    "SmsResponse",
    notification_response_base,
    {
        "content": fields.Nested(
            api.model(
                "SmsContent",
                {
                    "body": fields.String(required=True, description="SMS body"),
                    "from_number": fields.String(required=True, description="Sender phone number"),
                },
            )
        )
    },
)

email_response = api.inherit(
    "EmailResponse",
    notification_response_base,
    {
        "content": fields.Nested(
            api.model(
                "EmailContent",
                {
                    "body": fields.String(required=True, description="Email body"),
                    "subject": fields.String(required=True, description="Email subject"),
                    "from_email": fields.String(required=True, description="Sender email"),
                },
            )
        )
    },
)

bulk_response = api.model(
    "BulkResponse",
    {
        "data": fields.Nested(
            api.model(
                "JobResponse",
                {
                    "id": fields.String(required=True, description="Job ID"),
                    "reference": fields.String(description="Job reference"),
                    "original_file_name": fields.String(description="Original filename"),
                    "template": fields.String(required=True, description="Template ID"),
                    "notification_count": fields.Integer(required=True, description="Number of notifications"),
                    "created_at": fields.DateTime(required=True, description="Creation time"),
                    "created_by": fields.String(required=True, description="Creator ID"),
                    "job_status": fields.String(required=True, description="Job status"),
                    "scheduled_for": fields.DateTime(description="When the job is scheduled to be processed"),
                },
            )
        )
    },
)
