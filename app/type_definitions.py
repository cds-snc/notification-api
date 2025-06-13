"""
TypedDict definitions auto-generated from Marshmallow schemas.
This eliminates duplication and ensures types stay in sync.
"""

from typing import Any, Dict, List, Optional, TypedDict


class ReportResponseDict(TypedDict, total=False):
    """Type definition auto-generated from ReportSchema"""

    id: Optional[str]
    requesting_user_id: Optional[str]
    report_type: Optional[str]
    service_id: Optional[str]
    status: Optional[str]
    requested_at: Optional[str]
    completed_at: Optional[str]
    expires_at: Optional[str]
    url: Optional[str]
    language: Optional[str]
    notification_statuses: Optional[List[Optional[str]]]
    job_id: Optional[str]
    requesting_user: Optional[Dict[str, Any]]


class ServiceReportsResponseDict(TypedDict):
    """Response wrapper for GET /service/{id}/report endpoint"""

    data: List[ReportResponseDict]


class CreateReportResponseDict(TypedDict):
    """Response wrapper for POST /service/{id}/report endpoint"""

    data: ReportResponseDict


class CreateReportRequestDict(TypedDict, total=False):
    """Request type for POST /service/{id}/report endpoint"""

    report_type: str
    requesting_user_id: Optional[str]  # UUID as string in JSON
    language: Optional[str]
    notification_statuses: Optional[List[str]]
    job_id: Optional[str]  # UUID as string in JSON


def _validate_type_schema_sync():
    """Runtime check to ensure TypedDict fields match ReportSchema fields."""
    from app.schemas import report_schema

    schema_fields = set(report_schema.fields.keys())
    typeddict_fields = set(ReportResponseDict.__annotations__.keys())

    missing_in_typeddict = schema_fields - typeddict_fields
    extra_in_typeddict = typeddict_fields - schema_fields

    if missing_in_typeddict:
        raise AssertionError(f"ReportResponseDict missing fields: {missing_in_typeddict}")

    if extra_in_typeddict:
        raise AssertionError(f"ReportResponseDict has extra fields: {extra_in_typeddict}")


# Export all types
__all__ = [
    "ReportResponseDict",
    "ServiceReportsResponseDict",
    "CreateReportRequestDict",
    "CreateReportResponseDict",
    "_validate_type_schema_sync",
]
