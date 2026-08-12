from app.schema_validation.definitions import uuid

remove_email_from_suppression_list_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST remove email from SES suppression list",
    "type": "object",
    "title": "Remove email from suppression list",
    "properties": {
        "email_address": {"type": "string", "format": "email_address"},
        "updated_by_id": uuid,
        "request_details": {"type": "string", "maxLength": 500},
    },
    "required": ["email_address", "updated_by_id"],
}
