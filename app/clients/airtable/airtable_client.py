from typing import Optional

from flask import current_app
from pyairtable import Api

from app.clients import Client


class AirtableClient(Client):
    """
    A barebones Airtable client that provides quick access to the pyairtable API.
    """

    def __init__(self, base_id: Optional[str] = None, table_name: Optional[str] = None):
        self.api_key = current_app.config.get("AIRTABLE_API_KEY")

        if not base_id and not table_name:
            self.api = Api(api_key=self.api_key)
        else:
            self.api = Api(api_key=self.api_key)
            self.base = self.api.base(str(base_id))
            self.table_name = table_name

    def _reconfigure(self, base_id: str, table_name: Optional[str] = None):
        """Reconfigure the Airtable client with a new base ID and optional table name."""
        self.base = self.api.base(base_id)
        if table_name:
            self.table_name = table_name

    def get_base_schema(self):
        """Get the base schema to check existing tables."""
        try:
            base = self.api.base(self.base_id)
            return base.schema()
        except Exception as e:
            print(f"Error getting base schema: {e}")
            raise

    def table_exists(self, table_name: Optional[str] = None) -> bool:
        try:
            for table in self.base.tables():
                if table.name == self.table_name:
                    return True
            return False
        except Exception as e:
            print(f"Error checking if table exists: {e}")
            return False
