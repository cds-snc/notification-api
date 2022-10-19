from datetime import datetime
from typing import Optional, TypedDict

from app.models import ApiKeyType, Job, NotificationType, Service

class NotificationDictToSign(TypedDict):
    id: str
    template: str
    service_id: str
    template_version: str
    to: str # recipient
    personalisation: Optional[dict]
    simulated: bool
    api_key: str
    key_type: ApiKeyType # should be ApiKeyType but I can't import that here
    client_reference: Optional[str]
    reply_to_text: str
    
class VerifiedNotification(NotificationDictToSign):
    service: Service
    notification_id: str
    template_id: str
    recipient: str # to
    notification_type: NotificationType
    api_key_id: Optional[str] # notification.get("api_key", None)
    created_at: datetime
    job_id: Optional[Job]
    job_row_number: Optional[int] 