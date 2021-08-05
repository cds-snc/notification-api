"""
Definitions are intended for schema definitions that are not likely to change from version to version.
If the definition is specific to a version put it in a definition file in the version package
"""

uuid = {
    "type": "string",
    "format": "validate_uuid",
    "validationMessage": "is not a valid UUID",
    "code": "1001",  # yet to be implemented
    "link": "link to our error documentation not yet implemented",
}

nullable_uuid = {
    "type": ["string", "null"],
    "format": "validate_uuid",
    "validationMessage": "is not a valid UUID",
    "code": "1001",  # yet to be implemented
    "link": "link to our error documentation not yet implemented",
}

personalisation = {
    "type": "object",
    "patternProperties": {
        "^.*$": {
            "type:": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "binaryEncoding": "base64",
                },
                "sending_method": {"type": "string", "enum": ["attach", "link"]},
            },
            "required": ["file", "sending_method"],
            "if": {"properties": {"sending_method": {"const": "attach"}}},
            "then": {
                "required": ["filename"],
                "properties": {"filename": {"minLength": 3, "maxLength": 255}},
            },
        }
    },
}

letter_personalisation = dict(
    personalisation,
    properties={
        "address_line_1": {
            "type": "string",
            "minLength": 1,
            "validationMessage": "address_line_1 is required",
        },
        "address_line_2": {
            "type": "string",
            "minLength": 1,
            "validationMessage": "address_line_2 is required",
        },
        "postcode": {
            "type": "string",
            "minLength": 1,
            "validationMessage": "postcode is required",
        },
    },
    required=["address_line_1", "address_line_2", "postcode"],
)

https_url = {
    "type": "string",
    "format": "uri",
    "pattern": "^https.*",
    "validationMessage": "is not a valid https url",
    "code": "1001",  # yet to be implemented
    "link": "link to our error documentation not yet implemented",
}
