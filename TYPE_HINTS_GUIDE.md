# Using Type Hints with the Reports API

This guide shows how to get full type hints when calling the Reports API from Python applications.

## Option 1: Using TypedDict (Recommended for most cases)

This approach provides type hints without runtime validation overhead:

```python
# In your calling application
import requests
from typing import cast
from notifications_api.response_models import ServiceReportsResponseDict, ReportResponseDict

def get_reports_with_types(service_id: str, api_key: str) -> ServiceReportsResponseDict:
    """Get service reports with full type hints"""
    response = requests.get(
        f"https://api.example.com/service/{service_id}/report",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"limit_days": 7}
    )
    response.raise_for_status()
    
    # Cast to typed response for IDE support
    return cast(ServiceReportsResponseDict, response.json())

# Usage with full type safety
reports = get_reports_with_types("123e4567-e89b-12d3-a456-426614174000", "api-key")

# IDE provides autocomplete and type checking
for report in reports['data']:  # Type: List[ReportResponseDict]
    print(f"Report {report['id']} has status {report['status']}")  # Full autocomplete
    if report.get('url'):  # Type checker knows this is Optional[str]
        download_file(report['url'])
```

## Option 2: Using Marshmallow Client (With Runtime Validation)

This approach provides both type hints and runtime validation using the existing schemas:

```python
from notifications_api.marshmallow_client import TypedReportsClient
from notifications_api.response_models import ServiceReportsResponseDict, CreateReportRequestDict

# Initialize client with validation
client = TypedReportsClient("https://api.example.com", "your-api-key")

try:
    # Get reports with validation and type hints
    reports: ServiceReportsResponseDict = client.get_service_reports(
        service_id="123e4567-e89b-12d3-a456-426614174000",
        limit_days=30
    )
    
    # Create new report with validation
    request_data: CreateReportRequestDict = {
        "report_type": "email",
        "language": "en",
        "notification_statuses": ["delivered", "failed"]
    }
    
    new_report = client.create_service_report(
        service_id="123e4567-e89b-12d3-a456-426614174000",
        request_data=request_data
    )
    
except requests.HTTPError as e:
    print(f"API error: {e}")
except ValidationError as e:
    print(f"Schema validation error: {e}")
```

## Option 3: Direct Schema Validation

Use the existing Marshmallow schemas directly for validation:

```python
import requests
from marshmallow import ValidationError
from notifications_api.schemas import report_schema
from notifications_api.response_models import validate_reports_list_response

# Make API call
response = requests.get("/service/uuid/report")
response.raise_for_status()

# Validate using existing schema
try:
    validated_data = validate_reports_list_response(response.json())
    # Now you have type-safe, schema-validated data
    for report in validated_data['data']:
        print(f"Validated report: {report['id']}")
except ValidationError as e:
    print(f"Response doesn't match expected schema: {e}")
```

## Setting Up in Your Project

### 1. Add types as a dependency

```toml
# pyproject.toml
[tool.poetry.dependencies]
notifications-api-types = {git = "https://github.com/your-org/notifications-api.git", subdirectory = "app"}
```

Or in requirements.txt:
```
-e git+https://github.com/your-org/notifications-api.git#egg=notifications-api&subdirectory=app
```

### 2. Use in your IDE

Your IDE (VS Code, PyCharm, etc.) will now provide:
- Autocomplete for all response fields
- Type checking to catch errors early  
- Documentation for each field
- Refactoring support

### 3. Type checking with mypy

```bash
# Run mypy to catch type errors
mypy your_application.py
```

## Benefits of This Approach

1. **Leverages Existing Schemas**: Uses your current Marshmallow schemas as the source of truth
2. **No Duplication**: TypedDict definitions mirror the schema fields exactly
3. **Runtime Validation**: Optional validation using existing business logic
4. **IDE Support**: Full autocomplete and type checking
5. **Maintainable**: Changes to schemas automatically update type definitions
6. **Lightweight**: TypedDict has no runtime overhead

## Type Definitions Available

- `ReportResponseDict`: Single report object
- `ServiceReportsResponseDict`: Response from GET /service/{id}/report  
- `CreateReportRequestDict`: Request for POST /service/{id}/report
- `CreateReportResponseDict`: Response from POST /service/{id}/report

All types match the existing `ReportSchema` Marshmallow schema exactly.
