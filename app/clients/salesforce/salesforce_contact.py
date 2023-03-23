from typing import Optional, Tuple

from flask import current_app
from simple_salesforce import Salesforce

from .salesforce_utils import get_name_parts, parse_result


def create(session: Salesforce, user, account_id: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Create a Salesforce Contact from the given Notify User

    Args:
        session (Salesforce): Salesforce session used to perform the operation.
        user (User): Notify User that has just been activated.
        account_id (str | None, optional): ID of the Account to associate the Contact with.

    Returns:
        Tuple[bool, Optional[str]]: Success indicator and the ID of the new Contact
    """
    is_created = False
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
        is_created = parse_result(result, f"Salesforce Contact create for '{user.email_address}'")
        contact_id = result.get("id")

    except Exception as ex:
        current_app.logger.error(f"Salesforce Contact create failed: {ex}")
    return (is_created, contact_id)
