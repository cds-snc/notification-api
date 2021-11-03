
update_service_whitelist_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "PUT request to replace service whitelist",
    "type": "object",
    "title": "Replace service whitelisted phone numbers and email addresses",
    "properties": {
        "email_addresses": {
            "type": "array",
            "items": {"type": "string"}
        },
        "phone_numbers": {
            "type": "array",
            "items": {"type": "string"}
        },
    },
    "required": ["email_addresses", "phone_numbers"],
    "additionalProperties": False
}
