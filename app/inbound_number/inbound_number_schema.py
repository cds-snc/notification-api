post_create_inbound_number_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST create inbound number schema",
    "type": "object",
    "properties": {
        "number": {"type": "string"},
        "provider": {"type": "string"},
        "service_id": {"type": "string"},
        "active": {"type": "boolean"},
        "url_endpoint": {"type": "string"},
        "self_managed": {"type": "boolean"},
    },
    "required": ["number", "provider"],
    "additionalProperties": False
}


post_update_inbound_number_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST update inbound number schema",
    "type": "object",
    "properties": {
        "number": {"type": "string"},
        "provider": {"type": "string"},
        "service_id": {"type": "string"},
        "active": {"type": "boolean"},
        "url_endpoint": {"type": "string"},
        "self_managed": {"type": "boolean"},
    },
    "additionalProperties": False
}
