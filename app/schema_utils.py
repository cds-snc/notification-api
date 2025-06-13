"""
Utilities for automatically generating TypedDict types from Marshmallow schemas.
This provides a clean way to eliminate duplication between schemas and types.
"""

from typing import Any, Dict, List, Optional, Type, TypedDict

from marshmallow import Schema, fields


class TypedDictFromSchemaMixin:
    """Mixin that adds TypedDict generation capabilities to Marshmallow schemas."""

    @classmethod
    def get_typeddict_class(cls, class_name: str = None) -> Type[TypedDict]:
        """Generate a TypedDict class from this schema."""
        if class_name is None:
            class_name = cls.__name__.replace("Schema", "Dict")

        # Create an instance to access fields
        schema_instance = cls()

        # Generate field annotations
        annotations = {}
        for field_name, field_obj in schema_instance.fields.items():
            annotations[field_name] = _field_to_type_annotation(field_obj)

        # Create and return TypedDict class
        return TypedDict(class_name, annotations, total=False)


def _field_to_type_annotation(field: fields.Field) -> type:
    """Convert Marshmallow field to Python type annotation for JSON serialization."""

    # Base type mapping for JSON serialization
    base_types = {
        fields.String: str,
        fields.Integer: int,
        fields.Float: float,
        fields.Boolean: bool,
        fields.DateTime: str,  # JSON datetime as ISO string
        fields.UUID: str,  # JSON UUID as string
        fields.Dict: Dict[str, Any],
        fields.Method: str,
    }

    field_type = type(field)

    # Handle List fields
    if isinstance(field, fields.List):
        if hasattr(field, "inner") and field.inner:
            inner_type = _field_to_type_annotation(field.inner)
            base_type = List[inner_type]  # type: ignore
        else:
            base_type = List[str]

    # Handle Nested fields
    elif isinstance(field, fields.Nested):
        base_type = Dict[str, Any]

    # Handle base field types
    else:
        base_type = base_types.get(field_type, str)

    # Wrap in Optional if field allows None or is not required
    if field.allow_none or not field.required:
        return Optional[base_type]  # type: ignore

    return base_type


def generate_response_types(schema_class: Type[Schema], base_name: str = None):
    """Generate common API response TypedDict classes from a schema."""
    if base_name is None:
        base_name = schema_class.__name__.replace("Schema", "")

    # Generate the main response type
    main_type = schema_class.get_typeddict_class(f"{base_name}Dict")

    # Generate list response type
    list_response_name = f"{base_name}sResponseDict"
    list_response_type = TypedDict(
        list_response_name,
        {
            "data": List[main_type]  # type: ignore
        },
    )

    # Generate single response type
    single_response_name = f"Create{base_name}ResponseDict"
    single_response_type = TypedDict(single_response_name, {"data": main_type})

    return {
        "main": main_type,
        "list_response": list_response_type,
        "single_response": single_response_type,
    }


# Example usage with existing schemas
def schema_typeddict(cls):
    """Class decorator to add TypedDict generation to Marshmallow schemas."""

    # Add the mixin functionality
    for attr_name in dir(TypedDictFromSchemaMixin):
        if not attr_name.startswith("_"):
            setattr(cls, attr_name, getattr(TypedDictFromSchemaMixin, attr_name))

    return cls
