from flask import url_for
from flask_restx import Api

from app.v2.notifications import v2_notification_blueprint


class CustomAPI(Api):
    @property
    def specs_url(self):
        """
        Override the default specs_url to use the url_for function
        """
        return url_for(self.endpoint("specs"))


# Initialize the API with metadata about your API
authorizations = {"apikey": {"type": "apiKey", "in": "header", "name": "Authorization"}}

api = CustomAPI(
    v2_notification_blueprint,
    version="2.0",
    title="GOV.UK Notify API",
    description="The GOV.UK Notify API lets you send emails, text messages and letters.",
    doc="/docs",
    authorizations=authorizations,
    security="apikey",
    prefix="/v2/notifications",
)

# Create namespaces for organizing operations
notifications_namespace = api.namespace("notifications", description="Notification operations")

# We'll define models for request and response schemas
bulk_notification_model = api.model(
    "BulkNotification",
    {
        # This will be defined later when setting up the models
    },
)

email_notification_model = api.model(
    "EmailNotification",
    {
        # This will be defined later when setting up the models
    },
)

sms_notification_model = api.model(
    "SMSNotification",
    {
        # This will be defined later when setting up the models
    },
)

letter_notification_model = api.model(
    "LetterNotification",
    {
        # This will be defined later when setting up the models
    },
)

precompiled_letter_notification_model = api.model(
    "PrecompiledLetterNotification",
    {
        # This will be defined later when setting up the models
    },
)
