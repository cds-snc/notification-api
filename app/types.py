from datetime import datetime
from typing import Optional

from app.encryption import NotificationDictToSign
from app.models import NotificationType, Service


class VerifiedNotification(NotificationDictToSign):
    service: Service
    notification_id: str
    template_id: str
    recipient: str  # to
    notification_type: NotificationType
    api_key_id: Optional[str]  # notification.get("api_key", None)
    created_at: datetime
    job_id: Optional[str]
    job_row_number: Optional[int]
