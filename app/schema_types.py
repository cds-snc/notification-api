"""
Auto-generated TypedDict definitions from Marshmallow schemas.
This module eliminates duplication by deriving types directly from schemas.
"""

from typing import Any, Dict, List, Optional, TypedDict, Union

from marshmallow import fields

from app.schemas import report_schema


def marshmallow_field_to_python_type(field: fields.Field) -> str:
    """Convert a Marshmallow field to its corresponding Python type string for JSON serialization."""

    # For JSON APIs, UUIDs and dates become strings
    type_mapping = {
        fields.String: "str",
        fields.Integer: "int",
        fields.Float: "float",
        fields.Boolean: "bool",
        fields.DateTime: "str",  # ISO datetime string in JSON
        fields.UUID: "str",  # UUID string in JSON
        fields.Dict: "Dict[str, Any]",
        fields.Method: "str",  # Method fields usually return strings
    }

    field_type = type(field)

    # Handle List fields
    if isinstance(field, fields.List):
        if hasattr(field, "inner") and field.inner:
            inner_type = marshmallow_field_to_python_type(field.inner)
            base_type = f"List[{inner_type}]"
        else:
            base_type = "List[str]"  # Default to string list

    # Handle Nested fields (become dicts in JSON)
    elif isinstance(field, fields.Nested):
        base_type = "Dict[str, Any]"

    # Handle other field types
    else:
        base_type = type_mapping.get(field_type, "str")

    # Make optional if field allows None or is not required
    if field.allow_none or not field.required:
        return f"Optional[{base_type}]"

    return base_type


def schema_to_typeddict_class(schema_instance, class_name: str) -> type:
    """Dynamically create a TypedDict class from a Marshmallow schema."""

    # Get field definitions from schema
    field_annotations = {}

    for field_name, field_obj in schema_instance.fields.items():
        python_type_str = marshmallow_field_to_python_type(field_obj)

        # Convert string type annotation to actual type
        # This is a simplified approach - in practice you might want more robust type resolution
        type_globals = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "List": List,
            "Dict": Dict,
            "Any": Any,
            "Optional": Optional,
            "Union": Union,
        }

        try:
            field_annotations[field_name] = eval(python_type_str, type_globals)
        except (NameError, SyntaxError):
            # Fallback to Any if type resolution fails
            field_annotations[field_name] = Any

    # Create TypedDict class dynamically
    return TypedDict(class_name, field_annotations, total=False)


# Auto-generate TypedDict classes from schemas
ReportResponseDict = schema_to_typeddict_class(report_schema, "ReportResponseDict")


# Manual wrapper types (these are simple and don't need generation)
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


# Export the auto-generated type for easy importing
__all__ = [
    "ReportResponseDict",
    "ServiceReportsResponseDict",
    "CreateReportResponseDict",
    "CreateReportRequestDict",
]
