from base64 import b64decode
from typing import Optional

from simple_salesforce import Salesforce

from . import salesforce_auth, salesforce_contact


class SalesforceClient:
    def init_app(self, app):
        self.client_id = app.config["SALESFORCE_CLIENT_ID"]
        self.username = app.config["SALESFORCE_USERNAME"]
        self.consumer_key = app.config["SALESFORCE_CLIENT_KEY"]
        self.privatekey = b64decode(app.config["SALESFORCE_CLIENT_PRIVATEKEY"])
        self.domain = app.config["SALESFORCE_DOMAIN"]

    #
    # Authentication
    #
    def get_session(self) -> Salesforce:
        return salesforce_auth.get_session(self.client_id, self.username, self.consumer_key, self.privatekey, self.domain)

    def end_session(self, session: Salesforce):
        salesforce_auth.end_session(session)

    #
    # Contacts
    #
    def contact_create(self, user, account_id: Optional[str] = None):
        session = self.get_session()
        salesforce_contact.create(session, user, account_id)
        self.end_session(session)
