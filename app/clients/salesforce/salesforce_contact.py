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


def create(session: Optional[Salesforce], user: User, field_updates: dict[str, Optional[str]]) -> Optional[str]:
    """Create a Salesforce Contact from the given Notify User

    Args:
        session (Salesforce): Salesforce session used to perform the operation.
        user (User): Notify User that has just been activated.
        field_updates (Optional[dict[str, str]]): Custom values used to override any default values.

    Returns:
        Optional[str]: Newly created Contact ID or None if the operation failed.
    """
    contact_id = None
    try:
        name_parts = get_name_parts(user.name)
        field_default_values = {
            "FirstName": name_parts["first"],
            "LastName": name_parts["last"],
            "Title": "created by Notify API",
            "CDS_Contact_ID__c": str(user.id),
            "Email": user.email_address,
        }
        field_values = field_default_values | field_updates
        result = session.Contact.create( # type: ignore
            field_values,
            headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
        )
        parse_result(result, f"Salesforce Contact create for '{user.email_address}'")
        contact_id = result.get("id")

    except Exception as ex:
        current_app.logger.error(f"SF_ERR Salesforce Contact create failed: {ex}")
    return contact_id


def update(session: Optional[Salesforce], user: User, field_updates: dict[str, Optional[str]]) -> Optional[str]:
    """Update a Contact's details.  If the Contact does not  exist, it is created.

    Args:
        session (Salesforce): Salesforce session used to perform the operation.
        user (User): Notify User object for the linked Contact to update
        field_updates (dict[str, Optional[str]]): The contact fields to update.

    Returns:
        contact_id (Optional[str]): ID of the updated Contact or None if the operation failed
    """
    contact_id = None
    try:
        contact = get_contact_by_user_id(session, str(user.id))

        # Existing contact, update the AccountID
        if contact:
            result = session.Contact.update( # type:ignore
                str(contact.get("Id")), field_updates, headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"}
            )
            parse_result(result, f"Salesforce Contact update '{user.email_address}' with '{field_updates}'")
            contact_id = contact.get("Id")
        # Create the new contact
        else:
            contact_id = create(session, user, field_updates)

    except Exception as ex:
        current_app.logger.error(f"SF_ERR Salesforce Contact update failed: {ex}")
    return contact_id


def get_contact_by_user_id(session: Optional[Salesforce], user_id: str) -> Optional[dict[str, str]]:
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
