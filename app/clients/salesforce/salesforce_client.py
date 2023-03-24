from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from simple_salesforce import Salesforce

from . import salesforce_auth, salesforce_contact

if TYPE_CHECKING:
    from app.models import User


class SalesforceClient:
    def init_app(self, app):
        self.client_id = app.config["SALESFORCE_CLIENT_ID"]
        self.username = app.config["SALESFORCE_USERNAME"]
        self.password = app.config["SALESFORCE_PASSWORD"]
        self.security_token = app.config["SALESFORCE_SECURITY_TOKEN"]
        self.domain = app.config["SALESFORCE_DOMAIN"]

    #
    # Authentication
    #
    def get_session(self) -> Salesforce:
        return salesforce_auth.get_session(self.client_id, self.username, self.password, self.security_token, self.domain)

    def end_session(self, session: Salesforce):
        salesforce_auth.end_session(session)

    #
    # Contacts
    #
    def contact_create(self, user: User, account_id: Optional[str] = None):
        session = self.get_session()
        salesforce_contact.create(session, user, account_id)
        self.end_session(session)
