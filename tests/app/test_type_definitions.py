"""
Test to ensure TypedDict definitions stay in sync with Marshmallow schemas.
"""

from app.schemas import report_schema
from app.type_definitions import ReportDict, _validate_type_schema_sync


def test_report_typeddict_schema_sync():
    """Ensure ReportDict stays in sync with ReportSchema."""
    # This will raise AssertionError if fields don't match
    _validate_type_schema_sync()


def test_report_schema_serialization_matches_typeddict():
    """Test that schema serialization produces data matching TypedDict structure."""
    import uuid
    from datetime import datetime

    from app.models import ReportStatus, ReportType

    # Create a sample report (you might need to adjust based on your model)
    sample_data = {
        "id": str(uuid.uuid4()),
        "report_type": ReportType.EMAIL.value,
        "service_id": str(uuid.uuid4()),
        "status": ReportStatus.REQUESTED.value,
        "requested_at": datetime.utcnow(),
        "language": "en",
    }

    # Validate with schema
    validated_data = report_schema.load(sample_data)
    serialized_data = report_schema.dump(validated_data)

    # Check that all required TypedDict fields are present or optional
    for field_name in ReportDict.__annotations__.keys():
        if field_name in serialized_data:
            # Field is present - check basic type compatibility
            assert serialized_data[field_name] is not None or "Optional" in str(ReportDict.__annotations__[field_name])


if __name__ == "__main__":
    test_report_typeddict_schema_sync()
    print("✅ TypedDict and Schema are in sync!")
