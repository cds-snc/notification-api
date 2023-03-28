from typing import Optional

from simple_salesforce import Salesforce

from .salesforce_utils import query_one, query_param_sanitize


def get_account_name_from_org(organisation_notes: str) -> str:
    """Given a service's organisation notes, returns the Account name
    which is the first segment of the organisation notes before the `>` character.
    If the notes do not contain a `>` character, the entire notes are returned.

    TODO: This could be improved by explicitly passing the selected Account name
    to the API from Admin rather than parsing it out of the organisation notes.

    Args:
        organisation_notes (str): The service's organisation notes

    Returns:
        str: The Account name
    """
    if isinstance(organisation_notes, str) and ">" in organisation_notes:
        return organisation_notes.split(">")[0].strip()
    return organisation_notes


def get_account_id_from_name(session: Salesforce, account_name: str, generic_account_id: str) -> Optional[str]:
    """Returns the Account ID for the given Account Name.  If no match is found, a generic
    Account not found ID is returned.

    Args:
        session (Salesforce): Salesforce session for the operation.
        account_name (str): Account name to lookup the ID for.
        generic_account_id (str): Generic Account ID to return if no match is found.

    Returns:
        Optional[str]: The matching Account ID or a generic Account ID if no match is found.
    """
    result = None
    if isinstance(account_name, str) and account_name.strip() != "":
        account_name_sanitized = query_param_sanitize(account_name)
        query = f"SELECT Id FROM Account where Name = '{account_name_sanitized}' OR CDS_AccountNameFrench__c = '{account_name_sanitized}' LIMIT 1"
        result = query_one(session, query)
    return result.get("Id") if result else generic_account_id
