from typing import Any, Optional

from flask import current_app
from simple_salesforce import Salesforce


def get_name_parts(full_name: str) -> dict[str, Optional[str]]:
    """
    Splits a space separated fullname into first and last
    name parts.  If the name cannot be split, the first
    name part will

    Args:
        full_name (str): The space seperated full name

    Returns:
        dict[str, str]: The first and last name parts
    """
    name_parts = full_name.split()
    return {
        "first": name_parts[0] if len(name_parts) > 0 else None,
        "last": " ".join(name_parts[1:]) if len(name_parts) > 1 else None,
    }


def query_one(query: str, session: Salesforce) -> Optional[dict[str, Any]]:
    """Execute an SOQL query that expects to return a single record.

    Args:
        query (str): The SOQL query to execute
        session (Salesforce): Authenticated Salesforce session

    Returns:
        dict[str, Any]: The result of the query or None
    """
    result = None
    try:
        results = session.query(query)
        if results.get("totalSize") == 1:
            result = results.get("records")[0]
        else:
            current_app.logger.warn(f"Salesforce no results found for query {query}")
    except Exception as ex:
        current_app.logger.error(f"Salesforce query {query} failed: {ex}")
    return result


def query_param_sanitize(param: str) -> str:
    """Escape single quotes from parameters that will be used in
    SOQL queries since these can cause injection attacks.

    Args:
        param (str): Parameter to sanitize

    Returns:
        str: Parameter with single quotes escaped
    """
    return param.replace("'", r"\'")


def parse_result(result: int | dict[str, Any], op: str) -> bool:
    """Parse a Salesforce API result object and log the result

    Args:
        result (int | dict[str, any]): Salesforce API result
        op (str): The operation we're logging

    Returns:
        bool: Did the operation work?
    """
    is_success = 200 <= result <= 299 if isinstance(result, int) else result.get("success", False)
    if is_success:
        current_app.logger.info(f"{op} succeeded")
    else:
        current_app.logger.error(f"{op} failed: {result}")
    return is_success


def get_account_id_by_name(account_name: str, account_data: list[dict[str, str]], current_lang: str) -> str:
    """Looks up an Account ID based on the given Account name and user's language.

    Args:
        account_name (str): Name of the account to lookup
        account_data (list[dict[str, str]]): List of all account data
        current_lang (str): The user's current language

    Returns:
        str: The account ID for the given account name.
    """
    name_attr = "name_fra" if current_lang == "fr" else "name_eng"
    account = [account for account in account_data if account[name_attr] == account_name]
    return account[0]["id"] if len(account) else current_app.config["SALESFORCE_GENERIC_ACCOUNT_ID"]
