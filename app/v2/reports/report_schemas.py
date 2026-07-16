from app.models import ReportType

post_report_request = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "POST v2 report request schema",
    "type": "object",
    "title": "POST v2/reports request",
    "properties": {
        "report_type": {"type": "string", "enum": [rt.value for rt in ReportType]},
    },
    "required": ["report_type"],
    "additionalProperties": False,
}
