from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

from simple_salesforce import Salesforce

from . import (
    salesforce_account,
    salesforce_auth,
    salesforce_contact,
    salesforce_engagement,
    salesforce_utils,
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
    def get_session(self) -> Optional[Salesforce]:
        """Returns an authenticated Salesforce session.

        Returns:
            Salesforce: The authenticated Salesforce session.
        """
        return salesforce_auth.get_session(self.client_id, self.username, self.password, self.security_token, self.domain)

    def end_session(self, session: Optional[Salesforce]) -> None:
        """Revokes a Salesforce session.

        Args:
            session (Salesforce): The Salesforce session to revoke.
        """
        salesforce_auth.end_session(session)

    #
    # Contacts
    #
    def contact_create(self, user: User) -> None:
        """Creates a Salesforce Contact for the given Notify user

        Args:
            user (User): The Notify user to create a Salesforce Contact for.
        """
        session = self.get_session()
        salesforce_contact.create(session, user, {})
        self.end_session(session)

    def contact_update(self, user: User) -> None:
        """Updates a Salesforce Contact for the given Notify user.  If the Contact does not exist, it is created.

        Args:
            user (User): The Notify user to update the Salesforce Contact for.
        """
        session = self.get_session()
        name_parts = salesforce_utils.get_name_parts(user.name)
        user_updates = {
            "FirstName": name_parts["first"],
            "LastName": name_parts["last"],
            "Email": user.email_address,
        }
        salesforce_contact.update(session, user, user_updates)
        self.end_session(session)

    def contact_update_account_id(self, session: Optional[Salesforce], service: Service, user: User) -> Tuple[Optional[str], Optional[str]]:
        """Updates the Account ID for the given Notify user's Salesforce Contact. The Salesforce Account ID
        and Contact ID are returned.

        Args:
            session (Salesforce): The Salesforce session to use for the operation.
            service (Service): The Notify service to retrieve the account from.
            user (User): The Notify user to update the Salesforce Contact for.  If a contact does not exist, one will be created.
        """
        account_name = salesforce_account.get_org_name_from_notes(service.organisation_notes)
        account_id = salesforce_account.get_account_id_from_name(session, account_name, self.generic_account_id)
        contact_id = salesforce_contact.update(session, user, {"AccountId": account_id})
        return account_id, contact_id

    #
    # Engagements
    #
    def engagement_create(self, service: Service, user: User) -> None:
        """Creates a Salesforce Engagement for the given Notify service.  The Engagement will
        be associated with the Notify user that created the Notify service.

        Args:
            service (Service): Notify Service to create an Engagement for.
            user (User): Notify User creating the service.
        """
        session = self.get_session()
        account_id, contact_id = self.contact_update_account_id(session, service, user)
        salesforce_engagement.create(session, service, {}, account_id, contact_id)
        self.end_session(session)

    def engagement_update(self, service: Service, user: User, field_updates: dict[str, str]) -> None:
        """Updates a Salesforce Engagement for the given Notify service.  The Engagement
        will be associated with the Notify user that triggers the stage update.

        Args:
            service (Service): Notify Service to update an Engagement for.
            user (User): Notify User creating the service.
            field_updates (dict[str, str]): The fields to update on the Engagement.
        """
        session = self.get_session()
        account_id, contact_id = self.contact_update_account_id(session, service, user)
        salesforce_engagement.update(session, service, field_updates, account_id, contact_id)
        self.end_session(session)

    def engagement_close(self, service: Service) -> None:
        """Closes a Salesforce Engagement for the given Notify service.

        Args:
            service (Service): Notify Service to close an Engagement for.
        """
        session = self.get_session()
        engagement = salesforce_engagement.get_engagement_by_service_id(session, str(service.id))
        if engagement:
            close_update = {
                "CDS_Close_Reason__c": "Service deleted by user",
                "StageName": salesforce_engagement.ENGAGEMENT_STAGE_CLOSED,
            }
            salesforce_engagement.update(session, service, close_update, None, None)
        self.end_session(session)

    def engagement_add_contact_role(self, service: Service, user: User) -> None:
        """Adds a Salesforce ContactRole to an Engagement.

        Args:
            service (Service): Notify Service that will have its Engagement's ContactRoles updated.
            user (User): Notify User being added as a ContactRole.
        """
        session = self.get_session()
        account_id, contact_id = self.contact_update_account_id(session, service, user)
        salesforce_engagement.contact_role_add(session, service, account_id, contact_id)
        self.end_session(session)

    def engagement_delete_contact_role(self, service: Service, user: User) -> None:
        """Deletes a Salesforce ContactRole from an Engagement.

        Args:
            service (Service): Notify Service that will have its Engagement's ContactRoles updated.
            user (User): Notify User being deleted as a ContactRole.
        """
        session = self.get_session()
        account_id, contact_id = self.contact_update_account_id(session, service, user)
        salesforce_engagement.contact_role_delete(session, service, account_id, contact_id)
        self.end_session(session)
