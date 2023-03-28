from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

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

    def contact_update_account_id(self, session: Salesforce, service: Service, user: User) -> Tuple[Optional[str], Optional[str]]:
        """Updates the Account ID for the given Notify user's Salesforce Contact. The Salesforce Account ID
        and Contact ID are returned.

        Args:
            session (Salesforce): The Salesforce session to use for the operation.
            service (Service): The Notify service to retrieve the account from.
            user (User): The Notify user to update the Salesforce Contact for.  If a contact does not exist, one will be created.
        """
        account_name = salesforce_account.get_account_name_from_org(service.organisation_notes)
        account_id = salesforce_account.get_account_id_from_name(session, account_name, self.generic_account_id)
        contact_id = salesforce_contact.update_account_id(session, user, account_id)
        return account_id, contact_id

    #
    # Engagements
    #
    def engagement_create(self, service: Service, user: User):
        """Creates a Salesforce Engagement for the given Notify service.  The Engagement will
        be associated with the Notify user that created the Notify service.

        Args:
            service (Service): Notify Service to create an Engagement for.
            user (User): Notify User creating the service.
        """
        session = self.get_session()
        account_id, contact_id = self.contact_update_account_id(session, service, user)
        salesforce_engagement.create(session, service, salesforce_engagement.ENGAGEMENT_STAGE_TRIAL, account_id, contact_id)
        self.end_session(session)

    def engagement_update_stage(self, service: Service, user: User, stage_name: str):
        """Updates the stage of a Salesforce Engagement for the given Notify service.  The Engagement
        will be associated with the Notify user that triggers the stage update.

        Args:
            service (Service): Notify Service to update an Engagement for.
            user (User): Notify User creating the service.
            stage_name (str): New stage to set.
        """
        session = self.get_session()
        account_id, contact_id = self.contact_update_account_id(session, service, user)
        salesforce_engagement.update_stage(session, service, stage_name, account_id, contact_id)
        self.end_session(session)
