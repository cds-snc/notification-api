from app.models import FILE_STATUSES, FILE_TYPES
from app.schema_validation.definitions import uuid

post_create_file_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST schema for creating a File",
    "type": "object",
    "properties": {
        "type": {"enum": FILE_TYPES},
        "name": {"type": "string", "minLength": 3, "maxLength": 255},
        "mime_type": {"type": "string", "minLength": 1},
        "file_size": {"type": "integer", "minimum": 0},
        "file_data": {
            "type": "string",
            "binaryEncoding": "base64",
        },
        "created_by": uuid,
    },
    "required": ["template_id", "type", "name", "mime_type", "file_size", "file_data", "created_by"],
}

post_update_file_status_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST schema for updating File status",
    "type": "object",
    "properties": {
        "service_id": uuid,
        "document_id": uuid,
        "status": {"enum": FILE_STATUSES},
    },
    "required": ["status"],
}


guardduty_scan_verdict_callback_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST schema for transformed GuardDuty scan verdict callback payload",
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "event_id": {"type": "string"},
        "event_time": {"type": "string"},
        "account": {"type": "string"},
        "region": {"type": "string"},
        "bucket_name": {"type": "string"},
        "object_key": {
            "type": "string",
            "pattern": r"^/?template_attachments/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        },
        "scan_status": {"type": "string", "enum": ["COMPLETED", "FAILED"]},
        "scan_result_status": {"type": "string"},
    },
    "required": ["object_key", "scan_status", "bucket_name"],
}
