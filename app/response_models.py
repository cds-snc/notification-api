"""
Response type definitions for API endpoints.
These are now auto-generated from Marshmallow schemas to eliminate duplication.
"""

# Import the auto-generated types that stay in sync with schemas
from app.type_definitions import (
    CreateReportRequestDict,
    CreateReportResponseDict,
    ServiceReportsResponseDict,
    _validate_type_schema_sync,
)
from app.type_definitions import (
    ReportResponseDict as ReportDict,
)

# Re-export with consistent naming
ReportResponseDict = ReportDict

# Export all the types
__all__ = [
    "ReportDict",
    "ReportResponseDict",
    "ServiceReportsResponseDict",
    "CreateReportRequestDict",
    "CreateReportResponseDict",
    "_validate_type_schema_sync",
]
