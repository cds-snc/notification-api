service_template_stats_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "service stats for specific template request schema",
    "type": "object",
    "title": "Service template stats request",
    "properties": {
        "start_date": {"type": ["string", "null"], "format": "date"},
        "end_date": {"type": ["string", "null"], "format": "date"},
    }
}
