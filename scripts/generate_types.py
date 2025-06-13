#!/usr/bin/env python3
"""
Generate TypedDict definitions from existing Marshmallow schemas.
This ensures type definitions stay in sync with the actual schemas.
"""

import sys

# Add the app directory to Python path
sys.path.insert(0, "/workspace")

from marshmallow import fields

from app.schemas import report_schema


def marshmallow_field_to_python_type(field, optional=False):
    """Convert Marshmallow field to Python type annotation string for JSON serialization"""

    # Base type mapping for JSON APIs (UUIDs/dates become strings)
    type_map = {
        fields.String: "str",
        fields.Integer: "int",
        fields.Float: "float",
        fields.Boolean: "bool",
        fields.DateTime: "str",  # JSON serializes to ISO string
        fields.UUID: "str",  # JSON serializes to string
        fields.List: "List",
        fields.Dict: "Dict[str, Any]",
        fields.Method: "str",  # Methods usually return strings
        fields.Nested: "Dict[str, Any]",  # Nested objects become dicts in JSON
    }

    field_type = type(field)
    base_type = type_map.get(field_type, "str")

    # Handle List fields
    if isinstance(field, fields.List):
        if hasattr(field, "inner") and field.inner:
            inner_type = marshmallow_field_to_python_type(field.inner)
            base_type = f"List[{inner_type}]"
        else:
            base_type = "List[str]"

    # Handle optional fields
    if optional or field.allow_none or not field.required:
        return f"Optional[{base_type}]"

    return base_type


def generate_typeddict_from_schema(schema, class_name):
    """Generate TypedDict code from a Marshmallow schema"""

    print(f"class {class_name}(TypedDict, total=False):")
    print(f'    """Type definition auto-generated from {schema.__class__.__name__}"""')

    # Get all fields from the schema
    schema_fields = schema.fields

    for field_name, field_obj in schema_fields.items():
        # Determine if field is optional
        is_optional = field_obj.allow_none or not field_obj.required

        # Get Python type
        python_type = marshmallow_field_to_python_type(field_obj, is_optional)

        # Add field to class
        print(f"    {field_name}: {python_type}")

    print()


def generate_sync_validation_function():
    """Generate a function to validate TypedDict stays in sync with schema"""

    print("""def _validate_type_schema_sync():
    '''Runtime check to ensure TypedDict fields match ReportSchema fields.'''
    from app.schemas import report_schema

    schema_fields = set(report_schema.fields.keys())
    typeddict_fields = set(ReportResponseDict.__annotations__.keys())

    missing_in_typeddict = schema_fields - typeddict_fields
    extra_in_typeddict = typeddict_fields - schema_fields

    if missing_in_typeddict:
        raise AssertionError(f"ReportResponseDict missing fields: {missing_in_typeddict}")

    if extra_in_typeddict:
        raise AssertionError(f"ReportResponseDict has extra fields: {extra_in_typeddict}")
""")


def main():
    """Generate all TypedDict definitions with sync validation"""
    print('"""')
    print("TypedDict definitions auto-generated from Marshmallow schemas.")
    print("This eliminates duplication and ensures types stay in sync.")
    print('"""')
    print("from typing import Any, Dict, List, Optional, TypedDict")
    print()

    # Generate ReportResponseDict from report_schema
    generate_typeddict_from_schema(report_schema, "ReportResponseDict")

    # Generate response wrapper types
    print("class ServiceReportsResponseDict(TypedDict):")
    print('    """Response wrapper for GET /service/{id}/report endpoint"""')
    print("    data: List[ReportResponseDict]")
    print()

    print("class CreateReportResponseDict(TypedDict):")
    print('    """Response wrapper for POST /service/{id}/report endpoint"""')
    print("    data: ReportResponseDict")
    print()

    # Generate request type
    print("class CreateReportRequestDict(TypedDict, total=False):")
    print('    """Request type for POST /service/{id}/report endpoint"""')
    print("    report_type: str")
    print("    requesting_user_id: Optional[str]  # UUID as string in JSON")
    print("    language: Optional[str]")
    print("    notification_statuses: Optional[List[str]]")
    print("    job_id: Optional[str]  # UUID as string in JSON")
    print()

    # Generate validation function
    generate_sync_validation_function()

    print()
    print("# Export all types")
    print("__all__ = [")
    print("    'ReportResponseDict',")
    print("    'ServiceReportsResponseDict',")
    print("    'CreateReportRequestDict',")
    print("    'CreateReportResponseDict',")
    print("    '_validate_type_schema_sync',")
    print("]")


if __name__ == "__main__":
    main()
