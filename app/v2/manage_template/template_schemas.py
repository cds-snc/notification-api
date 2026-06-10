from app.models import EMAIL_TYPE, SMS_TYPE
from app.schema_validation.definitions import uuid

post_manage_template_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST schema for creating a manage template",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "template_type": {"enum": [SMS_TYPE, EMAIL_TYPE]},
        "content": {"type": "string"},
        "subject": {"type": "string"},
        "template_category_id": uuid,
        "parent_folder_id": uuid,
    },
    "required": ["name", "template_type", "content", "template_category_id"],
    "if": {"properties": {"template_type": {"enum": [EMAIL_TYPE]}}},
    "then": {"required": ["subject"]},
    "additionalProperties": False,
}

template_categories_response = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "GET schema for listing manage template categories",
    "type": "object",
    "properties": {
        "template_categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "template_category_id": uuid,
                    "name": {"type": "string"},
                },
                "required": ["template_category_id", "name"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["template_categories"],
    "additionalProperties": False,
}
