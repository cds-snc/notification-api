"""
Type-safe client utilities for working with the Reports API using existing Marshmallow schemas.
This approach leverages the existing ReportSchema for consistent type definitions.
"""

from typing import Any, Dict, TypeVar

import requests

# TypedDict types for responses (can be imported by calling applications)
from app.response_models import CreateReportRequestDict, CreateReportResponseDict, ReportResponseDict, ServiceReportsResponseDict

# Import the existing Marshmallow schema
from app.schemas import report_schema

T = TypeVar("T")


class TypedReportsClient:
    """
    Type-safe client for the Reports API that uses the existing Marshmallow schema
    for validation and provides TypedDict types for static analysis.
    """

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def get_service_reports(self, service_id: str, limit_days: int = 7) -> ServiceReportsResponseDict:
        """
        Get reports for a service with full type hints.

        Args:
            service_id: The service UUID
            limit_days: Number of days to look back (default 7)

        Returns:
            ServiceReportsResponseDict: Typed response with list of reports

        Raises:
            requests.HTTPError: If the API request fails
            ValidationError: If the response doesn't match the expected schema
        """
        url = f"{self.base_url}/service/{service_id}/report"
        params = {"limit_days": limit_days}

        response = self.session.get(url, params=params)
        response.raise_for_status()

        data = response.json()

        # Validate the response using the existing Marshmallow schema
        reports_data = data.get("data", [])
        validated_reports = report_schema.load(reports_data, many=True)

        # Dump back to ensure consistent format
        serialized_reports = report_schema.dump(validated_reports, many=True)

        return {"data": serialized_reports}

    def create_service_report(self, service_id: str, request_data: CreateReportRequestDict) -> CreateReportResponseDict:
        """
        Create a new report for a service.

        Args:
            service_id: The service UUID
            request_data: The report creation request

        Returns:
            CreateReportResponseDict: Typed response for the created report

        Raises:
            requests.HTTPError: If the API request fails
            ValidationError: If the request/response doesn't match the expected schema
        """
        url = f"{self.base_url}/service/{service_id}/report"

        # Validate the request data (optional, but recommended)
        self._validate_create_request(request_data)

        response = self.session.post(url, json=request_data)
        response.raise_for_status()

        data = response.json()

        # Validate the response using the existing Marshmallow schema
        report_data = data.get("data")
        validated_report = report_schema.load(report_data)
        serialized_report = report_schema.dump(validated_report)

        return {"data": serialized_report}

    def _validate_create_request(self, request_data: CreateReportRequestDict) -> None:
        """Validate create request data using schema validation logic"""
        # You could add request validation here if needed
        required_fields = ["report_type"]
        for field in required_fields:
            if field not in request_data:
                raise ValueError(f"Missing required field: {field}")


def validate_report_response(data: Dict[str, Any]) -> ReportResponseDict:
    """
    Validate a single report response using the existing Marshmallow schema.

    Args:
        data: Raw response data from the API

    Returns:
        ReportResponseDict: Validated and typed report data

    Raises:
        ValidationError: If the data doesn't match the expected schema
    """
    validated = report_schema.load(data)
    return report_schema.dump(validated)


def validate_reports_list_response(data: Dict[str, Any]) -> ServiceReportsResponseDict:
    """
    Validate a list of reports response using the existing Marshmallow schema.

    Args:
        data: Raw response data from the API (should have 'data' key with list of reports)

    Returns:
        ServiceReportsResponseDict: Validated and typed reports list data

    Raises:
        ValidationError: If the data doesn't match the expected schema
    """
    reports_data = data.get("data", [])
    validated_reports = report_schema.load(reports_data, many=True)
    serialized_reports = report_schema.dump(validated_reports, many=True)
    return {"data": serialized_reports}


# Example usage for calling applications:
"""
from reports_marshmallow_client import TypedReportsClient, validate_reports_list_response
from app.response_models import ServiceReportsResponseDict, ReportResponseDict

# Initialize client
client = TypedReportsClient("https://api.example.com", "your-api-key")

# Get reports with full type hints and validation
try:
    reports: ServiceReportsResponseDict = client.get_service_reports(
        service_id="123e4567-e89b-12d3-a456-426614174000",
        limit_days=30
    )

    # IDE will provide autocomplete for all fields
    for report in reports['data']:  # Type: List[ReportResponseDict]
        print(f"Report {report['id']} status: {report['status']}")
        if report.get('url'):
            print(f"Download URL: {report['url']}")

except requests.HTTPError as e:
    print(f"API error: {e}")
except ValidationError as e:
    print(f"Schema validation error: {e}")

# Alternative: validate raw API responses
import requests

response = requests.get("/service/uuid/report")
if response.status_code == 200:
    validated_data: ServiceReportsResponseDict = validate_reports_list_response(response.json())
    # Now you have type-safe, schema-validated data
"""
