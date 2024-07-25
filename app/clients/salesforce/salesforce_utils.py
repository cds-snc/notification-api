from typing import Any, Optional

from flask import current_app
from simple_salesforce import Salesforce


def get_name_parts(full_name: str) -> dict[str, str]:
    """
    Splits a space separated fullname into first and last
    name parts.  If the name cannot be split, the first name will
    be blank and the last name will be set to the passed in full name.

    This is because Salesforce requires a last name but allows the
    last name to be blank.

    Args:
        full_name (str): The space seperated full name

    Returns:
        dict[str, str]: The first and last name parts
    """
    name_parts = full_name.split()
    return {
        "first": name_parts[0] if len(name_parts) > 1 else "",
        "last": " ".join(name_parts[1:]) if len(name_parts) > 1 else full_name,
    }


def query_one(session: Optional[Salesforce], query: str) -> Optional[dict[str, Any]]:
    """Execute an SOQL query that expects to return a single record.

    Args:
        query (str): The SOQL query to execute
        session (Salesforce): Authenticated Salesforce session

    Returns:
        dict[str, Any]: The result of the query or None
    """
    result = None
    try:
        if session is not None:
            results = session.query(query)
            if results.get("totalSize") == 1:
                result = results.get("records")[0]
            else:
                current_app.logger.warn(f"SF_WARN Salesforce no results found for query {query}")
        else:
            current_app.logger.error("SF_ERR Salesforce session is None")
    except Exception as ex:
        current_app.logger.error(f"SF_ERR Salesforce query {query} failed: {ex}")
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
        current_app.logger.error(f"SF_ERR {op} failed: {result}")
    return is_success
