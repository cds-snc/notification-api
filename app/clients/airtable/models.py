import os
from datetime import datetime
from enum import Enum
from typing import Any, Dict

# from flask import current_app
from pyairtable.orm import Model
from pyairtable.orm import fields as F
from pyairtable.orm.model import SaveResult


class AirtableTableMixin:
    """A mixin used in conjunction with the pyairtable.orm.Model class that provides table management
    capabilities, notably the ability to check if a table exists and create it automatically based on
    the current model's schema.
    """

    @classmethod
    def table_exists(cls) -> bool:
        """Uses the table name defined by the implementing model to check if the table exists in the target Airtable base."""
        if not hasattr(cls, "meta"):
            raise AttributeError("Model must have a meta attribute")

        table_name = cls.meta.table_name
        tables = cls.meta.base.tables()

        return any(table.name == table_name for table in tables)

    @classmethod
    def get_table_schema(cls) -> Dict[str, Any]:
        """Defines the table schema associated with the model. Used to create the table prior to a CRUD operation if it does not exist."""
        raise NotImplementedError("Subclasses must implement get_table_schema")

    @classmethod
    def create_table(cls) -> None:
        """Create the table in Airtable using the defined schema."""
        if not hasattr(cls, "meta"):
            raise AttributeError("Model must have a meta attribute")

        schema = cls.get_table_schema()
        base = cls.meta.base
        base.create_table(schema["name"], fields=schema["fields"])


class NewsletterSubscriber(Model, AirtableTableMixin):
    """
    Model representing a newsletter subscriber in Airtable. Leverages pyairtable's ORM capabilities making the models, behave similarly to SQLAlchemy models.
    See the [pyairtable documentation](https://pyairtable.readthedocs.io/en/stable/orm.html) for more details.

    Examples:
    ```python
        # Load an existing subscriber by their record ID
        NewsletterSubscriber.from_id("recXXXXXXXX")
        # Get all subscribers
        NewsletterSubscriber.all()
    ```
    """

    def __init__(self, **kwargs):
        self.email = kwargs.get("email", None)
        self.language = kwargs("language", self.Languages.EN.value)
        self.status = kwargs.get("status", self.Statuses.UNCONFIRMED.value)
        self.created_at = kwargs.get("created_at", datetime.now())

        if not self.email:
            raise ValueError("Email is required to create a NewsletterSubscriber")

        # Call the mixin to ensure the MailingList table exists before we operate on it.
        if not self.table_exists():
            self.create_table()

        super().__init__(**kwargs)

    # Define the fields
    email = F.RequiredTextField("Email")
    language = F.RequiredSelectField("Language")
    status = F.RequiredSelectField("Status")
    created_at = F.DatetimeField("Created At")
    confirmed_at = F.DatetimeField("Confirmed At")
    unsubscribed_at = F.DatetimeField("Unsubscribed At")
    has_resubscribed = F.CheckboxField("HasResubscribed")

    @classmethod
    def get_by_email(cls, email: str):
        """Find a subscriber by email address."""
        try:
            results = cls.all(formula=f"{{Email}} = '{email}'")
            return results[0] if results else None
        except Exception as e:
            print(f"Error finding subscriber by email: {e}")
            return None

    @classmethod
    def get_id_by_email(cls, email: str):
        """Get the record ID of a subscriber by email address."""
        subscriber = cls.get_by_email(email)
        return subscriber.id if subscriber else None

    def confirm_subscription(self) -> SaveResult:
        """Confirm this subscriber's subscription."""
        self.status = self.Statuses.SUBSCRIBED.value
        self.confirmed_at = datetime.now()
        return self.save()

    def unsubscribe_user(self) -> SaveResult:
        """Unsubscribe the current user."""
        self.status = self.Statuses.UNSUBSCRIBED.value
        self.unsubscribed = datetime.now()
        self.confirmed_at = None
        return self.save()

    def update_language(self, new_language: str) -> SaveResult:
        """Update the subscriber's language preference."""
        if not self.Languages.__contains__(self.status):
            raise ValueError(f"Cannot change language for subscriber with status: {self.status}")

        self.language = new_language
        return self.save()

    def reactivate_subscription(self, language: str) -> SaveResult:
        """Reactivate an unsubscribed user."""
        self.status = self.Statuses.SUBSCRIBED.value
        self.language = language
        self.has_resubscribed = True
        return self.save()

    @classmethod
    def get_table_schema(cls) -> Dict[str, Any]:
        return {
            "name": cls.Meta.table_name,
            "fields": [
                {"name": "Email", "type": "singleLineText"},
                {
                    "name": "Language",
                    "type": "singleSelect",
                    "options": {"choices": [{"name": cls.Languages.EN.value}, {"name": cls.Languages.FR.value}]},
                },
                {
                    "name": "Status",
                    "type": "singleSelect",
                    "options": {
                        "choices": [
                            {"name": cls.Statuses.UNCONFIRMED.value, "color": "yellowBright"},
                            {"name": cls.Statuses.SUBSCRIBED.value, "color": "greenBright"},
                            {"name": cls.Statuses.UNSUBSCRIBED.value, "color": "redBright"},
                        ]
                    },
                },
                {
                    "name": "Created At",
                    "type": "dateTime",
                    "options": {"dateFormat": {"name": "iso"}, "timeFormat": {"name": "24hour"}, "timeZone": "utc"},
                },
                {
                    "name": "Confirmed At",
                    "type": "dateTime",
                    "options": {"dateFormat": {"name": "iso"}, "timeFormat": {"name": "24hour"}, "timeZone": "utc"},
                },
                {
                    "name": "Unsubscribed At",
                    "type": "dateTime",
                    "options": {"dateFormat": {"name": "iso"}, "timeFormat": {"name": "24hour"}, "timeZone": "utc"},
                },
                {"name": "Has Resubscribed", "type": "checkbox", "options": {"icon": "check", "color": "grayBright"}},
            ],
        }

    class Languages(Enum):
        EN = "en"
        FR = "fr"

    class Statuses(Enum):
        UNCONFIRMED = "unconfirmed"
        SUBSCRIBED = "subscribed"
        UNSUBSCRIBED = "unsubscribed"

    class Meta:
        """Default meta data required by pyairtable's ORM to init an API client for the model."""

        api_key = os.environ.get("AIRTABLE_API_KEY")
        base_id = os.getenv(
            "AIRTABLE_BASE_ID",
        )
        table_name = os.getenv("AIRTABLE_MAILING_LIST_TABLE_NAME", "Notify Newsletter Mailing List")
