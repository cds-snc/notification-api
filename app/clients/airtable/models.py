from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict

from pyairtable.orm import Model
from pyairtable.orm import fields as F
from pyairtable.orm.model import SaveResult, _Meta
from requests import HTTPError, Response


class AirtableTableMixin:
    """A mixin enhancing the base pyairtable model functionality:
    1. Provides models with access to the Flask app context for configuration.
    2. Overrides the save method to ensure that the associated table exists before saving the model.
    3. Utilities for checking table state and fetching the model's table schema.
    """

    # Type annotation for mypy: classes using this mixin will always have a meta attribute as they will inherit from pyairtable.orm.Model
    if TYPE_CHECKING:
        meta: _Meta

    # Store the Flask app at the mixin level so all inheriting models can access it
    _flask_app = None

    def save(self, *, force: bool = False) -> SaveResult:
        """Override the save method to ensure the table exists before saving."""
        cls = type(self)
        if not cls.table_exists():
            cls.create_table()
        return super().save(force=force)  # type: ignore[misc]

    @classmethod
    def init_app(cls, app):
        """Initialize the mixin with Flask application context."""
        cls._flask_app = app

    @classmethod
    def _app(cls):
        """Get the Flask application context."""
        # TODO: Come up with some kind of ModelFactory that we can initialize with the app context and propagate to models
        # that it creates so we don't have to manually register every future model in app/__init__.py via init_app calls
        if cls._flask_app is None:
            raise RuntimeError("Flask app not initialized. Call init_app(app) first.")
        return cls._flask_app

    @classmethod
    def table_exists(cls) -> bool:
        """Uses the table name defined by the implementing model to check if the table exists in the target Airtable base."""
        if not hasattr(cls, "Meta"):
            raise AttributeError("Model must have a Meta attribute")

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


class NewsletterSubscriber(AirtableTableMixin, Model):
    """
    Model representing a newsletter subscriber in Airtable. Leverages pyairtable's ORM capabilities, the models behave similarly to SQLAlchemy models.
    See the [pyairtable documentation](https://pyairtable.readthedocs.io/en/stable/orm.html) for more details.
    """

    def __init__(self, **fields):
        """Initialize a newsletter subscriber.
        language defaults to: 'en'
        status defaults to: 'unconfirmed'
        """
        # Set defaults for language and status if not provided
        fields.setdefault("language", self.Languages.EN.value)
        fields.setdefault("status", self.Statuses.UNCONFIRMED.value)

        # Call parent constructor with the fields (including defaults)
        super().__init__(**fields)

    # Define the fields
    email = F.RequiredTextField("Email")
    language = F.RequiredSelectField("Language")
    status = F.RequiredSelectField("Status")
    created_at = F.DatetimeField("Created At")
    confirmed_at = F.DatetimeField("Confirmed At")
    unsubscribed_at = F.DatetimeField("Unsubscribed At")
    has_resubscribed = F.CheckboxField("Has Resubscribed")

    class Languages(Enum):
        EN = "en"
        FR = "fr"

    class Statuses(Enum):
        UNCONFIRMED = "unconfirmed"
        SUBSCRIBED = "subscribed"
        UNSUBSCRIBED = "unsubscribed"

    class Meta:
        """Default meta data required by pyairtable's ORM to init an API client for the model."""

        @staticmethod
        def api_key():
            return NewsletterSubscriber._app().config.get("AIRTABLE_API_KEY")

        @staticmethod
        def base_id():
            return NewsletterSubscriber._app().config.get("AIRTABLE_NEWSLETTER_BASE_ID")

        @staticmethod
        def table_name():
            return NewsletterSubscriber._app().config.get("AIRTABLE_NEWSLETTER_TABLE_NAME", "Mailing List")

    def save_unconfirmed_subscriber(self) -> SaveResult:
        """Save a new unconfirmed subscriber to the mailing list."""
        self.status = self.Statuses.UNCONFIRMED.value
        self.created_at = datetime.now()
        return self.save()

    def confirm_subscription(self) -> SaveResult:
        """Confirm this subscriber's subscription."""
        self.status = self.Statuses.SUBSCRIBED.value
        self.confirmed_at = datetime.now()
        return self.save()

    def unsubscribe_user(self) -> SaveResult:
        """Unsubscribe the current user."""
        self.status = self.Statuses.UNSUBSCRIBED.value
        self.unsubscribed_at = datetime.now()
        self.confirmed_at = None
        return self.save()

    def update_language(self, new_language: str) -> SaveResult:
        """Update the subscriber's language preference."""
        if new_language not in [lang.value for lang in self.Languages]:
            raise ValueError(f"Invalid language: {new_language}")

        self.language = new_language
        return self.save()

    def reactivate_subscription(self, language: str) -> SaveResult:
        """Reactivate an unsubscribed user."""
        self.status = self.Statuses.SUBSCRIBED.value
        self.language = language
        self.has_resubscribed = True
        self.confirmed_at = datetime.now()
        return self.save()

    @property
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "language": self.language,
            "status": self.status,
            "created_at": self.created_at,
            "confirmed_at": self.confirmed_at,
            "unsubscribed_at": self.unsubscribed_at,
            "has_resubscribed": self.has_resubscribed,
        }

    @classmethod
    def from_email(cls, email: str):
        """Find a subscriber by email address.

        Returns:
            NewsletterSubscriber: The subscriber with the given email.

        Raises:
            HTTPError: If the subscriber is not found (404) or other API errors occur.
        """
        results = cls.all(formula=f"{{Email}} = '{email}'")
        if not results:
            response = Response()
            response.status_code = 404
            raise HTTPError(response=response)
        return results[0]

    @classmethod
    def get_table_schema(cls) -> Dict[str, Any]:
        table_name = cls.meta.table_name
        return {
            "name": table_name,
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
