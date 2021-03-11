from dataclasses import dataclass, field, fields
from flask import escape

from typing import List

from notifications_utils.recipients import validate_email_address

__all__ = [
    'ContactRequest',
]


@dataclass
class ContactRequest:
    email_address: str = field()
    tags: List[str] = field(default_factory=lambda: list())
    name: str = field(default='')
    message: str = field(default='')
    user_profile: str = field(default='')
    department_org_name: str = field(default='')
    program_service_name: str = field(default='')
    intended_recipients: str = field(default='')
    main_use_case: str = field(default='')
    main_use_case_details: str = field(default='')
    friendly_support_type: str = field(default='')
    language: str = field(default='en')
    support_type: str = field(default='Support Request')

    def __post_init__(self):
        # email address is mandatory for us
        assert len(self.email_address), 'email can NOT be blank'
        validate_email_address(self.email_address)

        # HTML sanitize all fields that are string based
        for f in fields(self):
            try:
                if issubclass(f.type, str):
                    setattr(self, f.name, str(escape(getattr(self, f.name))))
            except TypeError:
                pass
