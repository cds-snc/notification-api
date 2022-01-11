from app.models import NOTIFICATION_STATUS_TYPES_COMPLETED, CALLBACK_CHANNEL_TYPES, SERVICE_CALLBACK_TYPES
from app.schema_validation.definitions import uuid, https_url

update_service_inbound_api_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST service callback/inbound api schema",
    "type": "object",
    "title": "Create service callback/inbound api",
    "properties": {
        "url": https_url,
        "bearer_token": {"type": "string", "minLength": 10},
        "notification_statuses": {
            "type": "array",
            "items": {
                "enum": NOTIFICATION_STATUS_TYPES_COMPLETED
            }
        },
        "updated_by_id": uuid
    },
    "required": ["updated_by_id"]
}

create_service_callback_api_request_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST service callback/inbound api schema",
    "type": "object",
    "title": "Create service callback/inbound api",
    "properties": {
        "url": https_url,
        "bearer_token": {"type": "string", "minLength": 10},
        "notification_statuses": {
            "type": "array",
            "items": {
                "enum": NOTIFICATION_STATUS_TYPES_COMPLETED
            }
        },
        "callback_type": {"enum": SERVICE_CALLBACK_TYPES},
        "callback_channel": {"enum": CALLBACK_CHANNEL_TYPES}
    },
    "required": ["url", "callback_channel", "callback_type"]
}

update_service_callback_api_request_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST service callback/inbound api schema",
    "type": "object",
    "title": "Update service callback/inbound api",
    "properties": {
        "url": https_url,
        "bearer_token": {"type": "string", "minLength": 10},
        "notification_statuses": {
            "type": "array",
            "items": {
                "enum": NOTIFICATION_STATUS_TYPES_COMPLETED
            }
        },
        "callback_type": {"enum": SERVICE_CALLBACK_TYPES},
        "callback_channel": {"enum": CALLBACK_CHANNEL_TYPES}
    },
    "anyOf": [
        {"required": ["url"]},
        {"required": ["bearer_token"]},
        {"required": ["notification_statuses"]}
    ]
}
