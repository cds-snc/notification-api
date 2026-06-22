# API Aggregation Query Patterns

- Prefer DAO-level aggregation helpers for analytics endpoints; keep route handlers thin.
- Scope all aggregation queries by `service_id` first, then apply optional date filters.
- Use SQLAlchemy `func` expressions (`count`, `sum`, `avg`) and explicit `group_by` fields.
- For categorical breakdowns, aggregate in SQL and return deterministic key order in Python.
- Use `Notification` for live/current data and `NotificationHistory` only when explicitly required by endpoint contract.
- Include only billable/terminal statuses if the endpoint contract requires it; otherwise aggregate over the explicit status set requested.
- Keep date filtering consistent: `created_at >= start_date` and `created_at < end_date` (half-open range).
- Return zeros for missing categories to keep response shape stable.

## Snippets

### DAO aggregation skeleton

```python
from sqlalchemy import case, func

from app.models import Notification


def get_<metric>_by_category(service_id, start_date=None, end_date=None):
    query = Notification.query.filter(Notification.service_id == service_id)

    if start_date is not None:
        query = query.filter(Notification.created_at >= start_date)
    if end_date is not None:
        query = query.filter(Notification.created_at < end_date)

    rows = (
        query.with_entities(
            Notification.notification_type,
            func.count(Notification.id).label("total"),
            func.sum(case((Notification.status == "delivered", 1), else_=0)).label("delivered"),
            func.sum(case((Notification.status == "failed", 1), else_=0)).label("failed"),
        )
        .group_by(Notification.notification_type)
        .all()
    )

    return rows
```

### Stable response shaping

```python
def build_breakdown(rows):
    breakdown = {"sms": 0, "email": 0, "letter": 0}
    for r in rows:
        breakdown[r.notification_type] = int(r.total or 0)
    return breakdown
```

### Date range schema pattern

```python
get_<metric>_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "type": "object",
    "properties": {
        "start_date": {"type": "string", "format": "date-time"},
        "end_date": {"type": "string", "format": "date-time"},
    },
}
```
