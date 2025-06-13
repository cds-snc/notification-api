"""
Client SDK for the Reports API with full type hints.
This can be installed as a package in calling applications.
"""

from datetime import datetime
from typing import List, Optional, Union
from uuid import UUID

import requests
from pydantic import BaseModel


class ReportResponse(BaseModel):
    """Response model for a single report"""

    id: UUID
    report_type: str
    service_id: UUID
    status: str
    requested_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    url: Optional[str] = None
    language: Optional[str] = None
    requesting_user_id: Optional[UUID] = None
    job_id: Optional[UUID] = None
    notification_statuses: Optional[List[str]] = None


class ServiceReportsResponse(BaseModel):
    """Response model for get_service_reports endpoint"""

    data: List[ReportResponse]


class CreateReportRequest(BaseModel):
    """Request model for creating a new report"""

    report_type: str
    requesting_user_id: Optional[UUID] = None
    language: Optional[str] = None
    notification_statuses: Optional[List[str]] = None
    job_id: Optional[UUID] = None


class ReportsAPIClient:
    """Type-safe client for the Reports API"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def get_service_reports(self, service_id: Union[str, UUID], limit_days: int = 7) -> ServiceReportsResponse:
        """
        Get reports for a service with type-safe response.

        Args:
            service_id: The service UUID
            limit_days: Number of days to look back (default 7)

        Returns:
            ServiceReportsResponse: Typed response with list of reports
        """
        url = f"{self.base_url}/service/{service_id}/report"
        params = {"limit_days": limit_days}

        response = self.session.get(url, params=params)
        response.raise_for_status()

        # Parse and validate response with Pydantic
        return ServiceReportsResponse.parse_obj(response.json())

    def create_service_report(self, service_id: Union[str, UUID], request_data: CreateReportRequest) -> ReportResponse:
        """
        Create a new report for a service with type-safe request/response.

        Args:
            service_id: The service UUID
            request_data: The report creation request

        Returns:
            ReportResponse: Typed response for the created report
        """
        url = f"{self.base_url}/service/{service_id}/report"

        response = self.session.post(url, data=request_data.json())
        response.raise_for_status()

        # Parse the response and extract the 'data' field
        response_data = response.json()
        return ReportResponse.parse_obj(response_data["data"])


# Usage example for calling applications:
"""
from reports_client import ReportsAPIClient, CreateReportRequest

# Initialize client
client = ReportsAPIClient("https://api.example.com", "your-api-key")

# Get reports with full type hints
reports: ServiceReportsResponse = client.get_service_reports(
    service_id="123e4567-e89b-12d3-a456-426614174000",
    limit_days=30
)

# IDE will provide autocomplete for all fields
for report in reports.data:
    print(f"Report {report.id} status: {report.status}")
    if report.url:
        print(f"Download URL: {report.url}")

# Create new report with type validation
request = CreateReportRequest(
    report_type="email",
    language="en",
    notification_statuses=["delivered", "failed"]
)

new_report: ReportResponse = client.create_service_report(
    service_id="123e4567-e89b-12d3-a456-426614174000",
    request_data=request
)
"""
