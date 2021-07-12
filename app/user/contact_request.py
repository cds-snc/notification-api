from dataclasses import dataclass, field, fields
from typing import List

from flask import escape
from notifications_utils.recipients import validate_email_address

__all__ = [
    "ContactRequest",
]


@dataclass
class ContactRequest:
    email_address: str = field()
    tags: List[str] = field(default_factory=lambda: list())
    name: str = field(default="")
    message: str = field(default="")
    user_profile: str = field(default="")
    department_org_name: str = field(default="")
    program_service_name: str = field(default="")
    intended_recipients: str = field(default="")
    main_use_case: str = field(default="")
    main_use_case_details: str = field(default="")
    friendly_support_type: str = field(default="Support Request")
    support_type: str = field(default="")
    language: str = field(default="en")
    service_name: str = field(default="")
    service_id: str = field(default="")
    service_url: str = field(default="")
    notification_types: str = field(default="")
    expected_volume: str = field(default="")

    def __post_init__(self):
        # email address is mandatory for us
        assert len(self.email_address), "email can NOT be blank"
        validate_email_address(self.email_address)

        # HTML sanitize all fields that are string based
        for f in fields(self):
            try:
                if issubclass(f.type, str):
                    setattr(self, f.name, str(escape(getattr(self, f.name))))
            except TypeError:
                pass

    def is_demo_request(self):
        return "demo" in self.support_type.lower()

    def is_go_live_request(self):
        return "go_live_request" in self.support_type.lower()
