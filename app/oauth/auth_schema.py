password_login_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "schema for password login post request",
    "type": "object",
    "title": "Password login request",
    "properties": {
        "email_address": {"type": ["string"]},
        "password": {"type": ["string"]},
    },
    "required": ["email_address", "password"]
}
