from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.encryption import NotificationDictToSign
from app.models import Job, NotificationType, Service


class VerifiedNotification(NotificationDictToSign):
    service: Service
    notification_id: str
    template_id: str
    recipient: str  # to
    notification_type: NotificationType
    api_key_id: Optional[str]  # notification.get("api_key", None)
    created_at: datetime
    job_id: Optional[Job]
    job_row_number: Optional[int]


@dataclass
class NotificationCallbackData:
    id: str
    to: str
    status: str
    formatted_status: str
    notification_type: str
    client_reference: Optional[str]
    provider_response: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    sent_at: Optional[datetime]
    service_id: str  # needed by the callback dispatch in nightly_tasks
