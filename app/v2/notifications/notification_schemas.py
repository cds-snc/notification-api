from app.models import (
    NOTIFICATION_STATUS_TYPES,
    NOTIFICATION_STATUS_LETTER_ACCEPTED,
    NOTIFICATION_STATUS_LETTER_RECEIVED,
    TEMPLATE_TYPES)
from app.schema_validation.definitions import (uuid, personalisation, letter_personalisation)
from app.va.identifier import IdentifierType
from app.mobile_app import MobileAppType

template = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "template schema",
    "type": "object",
    "title": "notification content",
    "properties": {
        "id": uuid,
        "version": {"type": "integer"},
        "uri": {"type": "string", "format": "uri"}
    },
    "required": ["id", "version", "uri"]
}

notification_by_id = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "GET notification response schema",
    "type": "object",
    "title": "response v2/notification",
    "properties": {
        "notification_id": uuid
    },
    "required": ["notification_id"]
}


get_notification_response = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "GET notification response schema",
    "type": "object",
    "title": "response v2/notification",
    "properties": {
        "id": uuid,
        "reference": {"type": ["string", "null"]},
        "email_address": {"type": ["string", "null"]},
        "phone_number": {"type": ["string", "null"]},
        "line_1": {"type": ["string", "null"]},
        "line_2": {"type": ["string", "null"]},
        "line_3": {"type": ["string", "null"]},
        "line_4": {"type": ["string", "null"]},
        "line_5": {"type": ["string", "null"]},
        "line_6": {"type": ["string", "null"]},
        "postcode": {"type": ["string", "null"]},
        "type": {"enum": ["sms", "letter", "email"]},
        "status": {"type": "string"},
        "template": template,
        "body": {"type": "string"},
        "subject": {"type": ["string", "null"]},
        "created_at": {"type": "string"},
        "sent_at": {"type": ["string", "null"]},
        "sent_by": {"type": ["string", "null"]},
        "completed_at": {"type": ["string", "null"]},
        "scheduled_for": {"type": ["string", "null"]}
    },
    "required": [
        # technically, all keys are required since we always have all of them
        "id", "reference", "email_address", "phone_number",
        "line_1", "line_2", "line_3", "line_4", "line_5", "line_6", "postcode",
        "type", "status", "template", "body", "created_at", "sent_at", "sent_by", "completed_at"
    ]
}

get_notifications_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "schema for query parameters allowed when getting list of notifications",
    "type": "object",
    "properties": {
        "reference": {"type": "string"},
        "status": {
            "type": "array",
            "items": {
                "enum": NOTIFICATION_STATUS_TYPES
                    + [NOTIFICATION_STATUS_LETTER_ACCEPTED + ', ' + NOTIFICATION_STATUS_LETTER_RECEIVED]
            }
        },
        "template_type": {
            "type": "array",
            "items": {
                "enum": TEMPLATE_TYPES
            }
        },
        "include_jobs": {"enum": ["true", "True"]},
        "older_than": uuid
    },
    "additionalProperties": False,
}

get_notifications_response = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "GET list of notifications response schema",
    "type": "object",
    "properties": {
        "notifications": {
            "type": "array",
            "items": {
                "type": "object",
                "$ref": "#/definitions/notification"
            }
        },
        "links": {
            "type": "object",
            "properties": {
                "current": {
                    "type": "string"
                },
                "next": {
                    "type": "string"
                }
            },
            "additionalProperties": False,
            "required": ["current"]
        }
    },
    "additionalProperties": False,
    "required": ["notifications", "links"],
    "definitions": {
        "notification": get_notification_response
    },

}

recipient_identifier = {
    "type": "object",
    "properties": {
        "id_type": {
            "type": "string",
            "enum": IdentifierType.values()
        },
        "id_value": {"type": "string"},
    },
    "required": ["id_type", "id_value"],
}

ICN_recipient_identifier = {
    "type": "object",
    "properties": {
        "id_type": {
            "type": "string",
            "enum": [IdentifierType.ICN.value]
        },
        "id_value": {"type": "string"},
    },
    "required": ["id_type", "id_value"],
}

post_sms_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST sms notification schema",
    "type": "object",
    "title": "POST v2/notifications/sms",
    "properties": {
        "reference": {"type": "string"},
        # This is the recipient's phone number.
        "phone_number": {"type": "string", "format": "phone_number"},
        # This can be used to look up the recipient's phone number.
        "recipient_identifier": recipient_identifier,
        # The template contains the sender's phone number.
        "template_id": uuid,
        "personalisation": personalisation,
        "scheduled_for": {"type": ["string", "null"], "format": "datetime_within_next_day"},
        "sms_sender_id": uuid,
        "billing_code": {"type": ["string", "null"], "maxLength": 256},
    },
    # This is necessary to get the content of the message and who it's from.
    "required": ["template_id"],
    # These attributes define who will receive the message.
    "anyOf": [
        {"required": ["phone_number"]},
        {"required": ["recipient_identifier"]}
    ],
    "additionalProperties": False,
    "validationMessage": {
        "anyOf": "Please provide either a phone number or recipient identifier."
    }
}

sms_content = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "content schema for SMS notification response schema",
    "type": "object",
    "title": "notification content",
    "properties": {
        "body": {"type": "string"},
        "from_number": {"type": "string"}
    },
    "required": ["body", "from_number"]
}

post_sms_response = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST sms notification response schema",
    "type": "object",
    "title": "response v2/notifications/sms",
    "properties": {
        "id": uuid,
        "reference": {"type": ["string", "null"]},
        "content": sms_content,
        "uri": {"type": "string", "format": "uri"},
        "template": template,
        "scheduled_for": {"type": ["string", "null"]}
    },
    "required": ["id", "content", "uri", "template"]
}


post_email_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST email notification schema",
    "type": "object",
    "title": "POST v2/notifications/email",
    "properties": {
        "reference": {"type": "string"},
        "email_address": {"type": "string", "format": "email_address"},
        "recipient_identifier": recipient_identifier,
        "template_id": uuid,
        "personalisation": personalisation,
        "scheduled_for": {"type": ["string", "null"], "format": "datetime_within_next_day"},
        "email_reply_to_id": uuid,
        "billing_code": {"type": ["string", "null"], "maxLength": 256}
    },
    "required": ["template_id"],
    "anyOf": [
        {"required": ["email_address"]},
        {"required": ["recipient_identifier"]}
    ],
    "additionalProperties": False,
    "validationMessage": {
        "anyOf": "Please provide either an email address or a recipient identifier"
    }
}

email_content = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "Email content for POST email notification",
    "type": "object",
    "title": "notification email content",
    "properties": {
        "body": {"type": "string"},
        "subject": {"type": "string"}
    },
    "required": ["body", "subject"]
}

post_email_response = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST email notification response schema",
    "type": "object",
    "title": "response v2/notifications/email",
    "properties": {
        "id": uuid,
        "reference": {"type": ["string", "null"]},
        "content": email_content,
        "uri": {"type": "string", "format": "uri"},
        "template": template,
        "scheduled_for": {"type": ["string", "null"]}
    },
    "required": ["id", "content", "uri", "template"]
}

post_letter_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST letter notification schema",
    "type": "object",
    "title": "POST v2/notifications/letter",
    "properties": {
        "reference": {"type": "string"},
        "template_id": uuid,
        "personalisation": letter_personalisation
    },
    "required": ["template_id", "personalisation"],
    "additionalProperties": False
}

post_precompiled_letter_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST precompiled letter notification schema",
    "type": "object",
    "title": "POST v2/notifications/letter",
    "properties": {
        "reference": {"type": "string"},
        "content": {"type": "string"},
        "postage": {"type": "string", "format": "postage"}
    },
    "required": ["reference", "content"],
    "additionalProperties": False
}

letter_content = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "Letter content for POST letter notification",
    "type": "object",
    "title": "notification letter content",
    "properties": {
        "body": {"type": "string"},
        "subject": {"type": "string"}
    },
    "required": ["body", "subject"]
}

post_letter_response = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST sms notification response schema",
    "type": "object",
    "title": "response v2/notifications/letter",
    "properties": {
        "id": uuid,
        "reference": {"type": ["string", "null"]},
        "content": letter_content,
        "uri": {"type": "string", "format": "uri"},
        "template": template,
        # letters cannot be scheduled
        "scheduled_for": {"type": "null"}
    },
    "required": ["id", "content", "uri", "template"]
}

push_notification_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "Send a push notification to a mobile app",
    "type": "object",
    "title": "POST v2/notifications/push",
    "properties": {
        "mobile_app": {
            "type": "string",
            "enum": MobileAppType.values()
        },
        "template_id": {"type": "string"},
        "recipient_identifier": ICN_recipient_identifier,
        "personalisation": personalisation,
    },
    "required": ["template_id", "recipient_identifier"],
    "additionalProperties": False
}
