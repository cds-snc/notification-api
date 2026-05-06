get_monthly_template_usage_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "GET monthly template usage schema",
    "title": "Get monthly template usage for a service",
    "type": "object",
    "properties": {
        "page": {"type": "integer", "minimum": 1},
        "page_size": {"type": "integer", "minimum": 10, "maximum": 100},
        "year": {"type": "integer"},
    },
    "required": ["year"],
}
