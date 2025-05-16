from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List, NewType, Optional

from app.models import Job, NotificationType, Service
from app.queue import QueueMessage

SignedNotification = NewType("SignedNotification", str)
SignedNotifications = NewType("SignedNotifications", List[SignedNotification])


@dataclass
class PendingNotification(QueueMessage):
    # todo: remove duplicate keys
    # todo: remove all NotRequired and decide if key should be there or not
    id: str
    template: str  # actually template_id
    service_id: str
    template_version: int
    to: str  # recipient
    personalisation: Optional[dict]
    simulated: bool
    api_key: str
    key_type: str  # should be ApiKeyType but can't import that here
    client_reference: Optional[str]
    reply_to_text: Optional[str]

    def to_dict(self) -> dict:
        """Convert the object to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        """Create an object from a dictionary."""
        return cls(**data)


@dataclass
class VerifiedNotification(PendingNotification):
    service: Service
    notification_id: str
    template_id: str
    recipient: str  # to
    notification_type: NotificationType
    api_key_id: Optional[str]  # notification.get("api_key", None)
    created_at: datetime
    job_id: Optional[Job]
    job_row_number: Optional[int]
    # postage: Optional[str]  # for letters
    # template_postage: Optional[str]  # for letters
