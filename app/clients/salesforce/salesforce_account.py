from typing import Optional

from simple_salesforce import Salesforce

from .salesforce_utils import query_one, query_param_sanitize

ORG_NOTES_ORG_NAME_INDEX = 0
ORG_NOTES_OTHER_NAME_INDEX = 1


def get_org_name_from_notes(organisation_notes: str, name_index: int = ORG_NOTES_ORG_NAME_INDEX) -> str:
    """Given a service's organisation notes, returns either the organisation name or
    organisation other name.  The organisation notes structure is as follows:

    ORG_NAME > ORG_OTHER_NAME

    If the `>` character is not found, the entire organisation notes is returned.

    TODO: This could be improved by explicitly passing the selected Account name
    to the API from Admin rather than parsing it out of the organisation notes.

    Args:
        organisation_notes (str): The service's organisation notes
        name_index (int): The index of the name to return.  Defaults to 0 (organisation name).

    Returns:
        str: The organisation name or organisation other name.
    """
    note_parts = organisation_notes.split(">") if isinstance(organisation_notes, str) else []
    if len(note_parts) > name_index:
        return note_parts[name_index].strip()
    return organisation_notes


def get_account_id_from_name(session: Optional[Salesforce], account_name: str, generic_account_id: str) -> Optional[str]:
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
