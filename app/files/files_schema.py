import uuid

from app.models import FILE_STATUSES, FILE_TYPES

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
    },
    "required": ["template_id", "type", "name", "mime_type", "file_size", "file_data"],
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
