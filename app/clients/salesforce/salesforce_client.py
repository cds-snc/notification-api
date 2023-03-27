from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from simple_salesforce import Salesforce

from . import (
    salesforce_account,
    salesforce_auth,
    salesforce_contact,
    salesforce_engagement,
)

if TYPE_CHECKING:
    from app.models import Service, User


class SalesforceClient:
    def init_app(self, app):
        self.client_id = app.config["SALESFORCE_CLIENT_ID"]
        self.username = app.config["SALESFORCE_USERNAME"]
        self.password = app.config["SALESFORCE_PASSWORD"]
        self.security_token = app.config["SALESFORCE_SECURITY_TOKEN"]
        self.domain = app.config["SALESFORCE_DOMAIN"]
        self.generic_account_id = app.config["SALESFORCE_GENERIC_ACCOUNT_ID"]

    #
    # Authentication
    #
    def get_session(self) -> Salesforce:
        """Returns an authenticated Salesforce session.

        Returns:
            Salesforce: The authenticated Salesforce session.
        """
        return salesforce_auth.get_session(self.client_id, self.username, self.password, self.security_token, self.domain)

    def end_session(self, session: Salesforce):
        """Revokes a Salesforce session.

        Args:
            session (Salesforce): The Salesforce session to revoke.
        """
        salesforce_auth.end_session(session)

    #
    # Contacts
    #
    def contact_create(self, user: User, account_id: Optional[str] = None):
        """Creates a Salesforce Contact for the given Notify user

        Args:
            user (User): The Notify user to create a Salesforce Contact for.
            account_id (Optional[str], optional): Salesforce Account ID to use for the Contact. Defaults to None.
        """
        session = self.get_session()
        salesforce_contact.create(session, user, account_id)
        self.end_session(session)

    #
    # Engagements
    #
    def engagement_create(self, service: Service, user: User):
        """Creates a Salesforce Engagement for the given Notify service

        Args:
            service (Service): Notify Service to create an Engagement for.
            user (User): Notify User creating the service.
        """
        session = self.get_session()
        account_name = salesforce_account.get_account_name_from_org(service.organisation_notes)
        account_id = salesforce_account.get_account_id_from_name(session, account_name, self.generic_account_id)
        contact_id = salesforce_contact.update_account_id(session, user, account_id)
        salesforce_engagement.create(session, service, salesforce_engagement.ENGAGEMENT_STAGE_TRIAL, account_id, contact_id)
        self.end_session(session)
