from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from flask import current_app
from simple_salesforce import Salesforce

from .salesforce_utils import (
    get_name_parts,
    parse_result,
    query_one,
    query_param_sanitize,
)

if TYPE_CHECKING:
    from app.models import User


def create(session: Salesforce, user: User, account_id: Optional[str]) -> Optional[str]:
    """Create a Salesforce Contact from the given Notify User

    Args:
        session (Salesforce): Salesforce session used to perform the operation.
        user (User): Notify User that has just been activated.
        account_id (str | None, optional): ID of the Account to associate the Contact with.

    Returns:
        Optional[str]: Newly created Contact ID or None if the operation failed.
    """
    contact_id = None
    try:
        name_parts = get_name_parts(user.name)
        result = session.Contact.create(
            {
                "FirstName": name_parts["first"] if name_parts["first"] else user.name,
                "LastName": name_parts["last"] if name_parts["last"] else "",
                "Title": "created by Notify API",
                "CDS_Contact_ID__c": str(user.id),
                "Email": user.email_address,
                "AccountId": account_id,
            },
            headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
        )
        parse_result(result, f"Salesforce Contact create for '{user.email_address}'")
        contact_id = result.get("id")

    except Exception as ex:
        current_app.logger.error(f"Salesforce Contact create failed: {ex}")
    return contact_id


def update_account_id(session: Salesforce, user: User, account_id: Optional[str]) -> Optional[str]:
    """Update the Account ID of a Contact.  If the Contact does not
    exist, it is created.

    Args:
        session (Salesforce): Salesforce session used to perform the operation.
        user (User): Notify User object for the linked Contact to update
        account_id (str): ID of the Salesforce Account

    Returns:
         contact_id (str): ID of the updated Contact or None if the operation failed
    """
    contact_id = None
    try:
        contact = get_contact_by_user_id(session, str(user.id))

        # Existing contact, update the AccountID
        if contact:
            result = session.Contact.update(
                contact.get("Id"), {"AccountId": account_id}, headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"}
            )
            parse_result(result, f"Salesforce Contact update '{user.email_address}' with account ID '{account_id}'")
            contact_id = contact.get("Id")
        # Create the new contact
        else:
            contact_id = create(session, user, account_id)

    except Exception as ex:
        current_app.logger.error(f"Salesforce Contact update failed: {ex}")
    return contact_id


def get_contact_by_user_id(session: Salesforce, user_id: str) -> Optional[dict[str, str]]:
    """Retrieve a Salesforce Contact by their Notify user ID.  If
    they can't be found, `None` is returned.

    Args:
        session (Salesforce): Salesforce session used to perform the operation.
        user_id (str): Notify user ID.

    Returns:
        Optional[dict[str, str]]: Salesforce Contact details or None if can't be found
    """
    result = None
    if isinstance(user_id, str) and user_id.strip():
        query = f"SELECT Id, FirstName, LastName, AccountId FROM Contact WHERE CDS_Contact_ID__c = '{query_param_sanitize(user_id)}' LIMIT 1"
        result = query_one(session, query)
    return result
