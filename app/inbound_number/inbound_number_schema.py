post_create_inbound_number_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST inbound number schema",
    "type": "object",
    "properties": {
        "number": {"type": "string"},
        "provider": {"type": "string"},
        "service_id": {"type": "string"},
        "active": {"type": ["boolean", "null"]}
    },
    "required": ["number", "provider", "service_id"]
}
