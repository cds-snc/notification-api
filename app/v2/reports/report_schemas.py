from app.models import ReportType
from app.schema_validation.definitions import nullable_uuid
from app.schema_validation.definitions import uuid as uuid_schema

get_report_by_id_request = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "schema for path parameters when getting a single report by id",
    "type": "object",
    "properties": {
        "report_id": uuid_schema,
    },
    "required": ["report_id"],
    "additionalProperties": False,
}

get_reports_request = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "schema for query parameters allowed when getting list of reports",
    "type": "object",
    "properties": {
        "older_than": uuid_schema,
    },
    "additionalProperties": False,
}

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
