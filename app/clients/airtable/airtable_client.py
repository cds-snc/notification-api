from typing import Optional

from pyairtable import Api


class AirtableClient:
    """
    A barebones Airtable client that provides quick access to the pyairtable API.
    Follows the Flask extension init_app() pattern.
    """

    def __init__(self):
        self.api_key: Optional[str] = None
        self.api: Optional[Api] = None

    def init_app(self, app):
        """Initialize the Airtable client with Flask application context."""
        self.api_key = app.config.get("AIRTABLE_API_KEY")

        if not self.api_key:
            app.logger.warning("AIRTABLE_API_KEY not configured")

        self.api = Api(api_key=self.api_key)
