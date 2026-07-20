from app.models import ReportType
from app.schema_validation.definitions import nullable_uuid, uuid as uuid_schema

post_report_request = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "POST v2 report request schema",
    "type": "object",
    "title": "POST v2/reports request",
    "properties": {
        "report_type": {"type": "string", "enum": [rt.value for rt in ReportType]},
        "language": {"type": "string", "enum": ["en", "fr"]},
        "job_id": nullable_uuid,
    },
    "required": ["report_type", "language"],
    "additionalProperties": False,
    "if": {"properties": {"report_type": {"const": "job"}}, "required": ["report_type"]},
    "then": {"properties": {"job_id": uuid_schema}, "required": ["job_id"]},
}
