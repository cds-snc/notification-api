from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from flask import current_app
from simple_salesforce import Salesforce

from .salesforce_account import ORG_NOTES_OTHER_NAME_INDEX, get_org_name_from_notes
from .salesforce_utils import parse_result, query_one, query_param_sanitize

if TYPE_CHECKING:
    from app.models import Service

ENGAGEMENT_PRODUCT = "GC Notify"
ENGAGEMENT_TEAM = "Platform"
ENGAGEMENT_TYPE = "New Business"
ENGAGEMENT_STAGE_ACTIVATION = "Activation"
ENGAGEMENT_STAGE_CLOSED = "Closed"
ENGAGEMENT_STAGE_LIVE = "Live"
ENGAGEMENT_STAGE_TRIAL = "Trial Account"


def create(
    session: Salesforce, service: Service, field_updates: dict[str, str], account_id: Optional[str], contact_id: Optional[str]
) -> Optional[str]:
    """Create a Salesforce Engagement for the given Notify service

    Args:
        session (Salesforce): Salesforce session to perform the operation.
        service (Service): The service's details for the engagement.
        field_updates (Optional[dict[str, str]]): Custom values used to override any default values.
        account_id (Optional[str]): Salesforce Account ID to associate with the Engagement.
        contact_id (Optional[str]): Salesforce Contact ID to associate with the Engagement.

    Returns:
       Optional[str]: Newly created Engagement ID or None if the operation failed.
    """
    engagement_id = None
    try:
        if account_id and contact_id:
            # Default Engagement values, which can be overridden by passing in field_updates
            field_default_values = {
                "Name": service.name,
                "AccountId": account_id,
                "ContactId": contact_id,
                "CDS_Opportunity_Number__c": str(service.id),
                "Notify_Organization_Other__c": get_org_name_from_notes(service.organisation_notes, ORG_NOTES_OTHER_NAME_INDEX),
                "CloseDate": datetime.today().strftime("%Y-%m-%d"),
                "RecordTypeId": current_app.config["SALESFORCE_ENGAGEMENT_RECORD_TYPE"],
                "StageName": ENGAGEMENT_STAGE_TRIAL,
                "Type": ENGAGEMENT_TYPE,
                "CDS_Lead_Team__c": ENGAGEMENT_TEAM,
                "Product_to_Add__c": ENGAGEMENT_PRODUCT,
            }
            field_values = field_default_values | field_updates
            result = session.Opportunity.create(
                engagement_maxlengths(field_values),
                headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
            )
            parse_result(result, f"Salesforce Engagement create for service ID {service.id}")
            engagement_id = result.get("id")

            # Create the Product association
            if engagement_id:
                result = session.OpportunityLineItem.create(
                    {
                        "OpportunityId": engagement_id,
                        "PricebookEntryId": current_app.config["SALESFORCE_ENGAGEMENT_STANDARD_PRICEBOOK_ID"],
                        "Product2Id": current_app.config["SALESFORCE_ENGAGEMENT_PRODUCT_ID"],
                        "Quantity": 1,
                        "UnitPrice": 0,
                    },
                    headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
                )
                parse_result(result, f"Salesforce Engagement OpportunityLineItem create for service ID {service.id}")
        else:
            current_app.logger.error(
                f"SF_ERR Salesforce Engagement create failed: missing Account ID '{account_id}' or Contact ID '{contact_id}' for service ID {service.id}"
            )
    except Exception as ex:
        current_app.logger.error(f"SF_ERR Salesforce Engagement create failed: {ex}")
    return engagement_id


def update(
    session: Salesforce, service: Service, field_updates: dict[str, str], account_id: Optional[str], contact_id: Optional[str]
) -> Optional[str]:
    """Update an Engagement.  If the Engagement does not exist, it is created.

    Args:
        session (Salesforce): Salesforce session to perform the operation.
        service (Service): The service's details for the engagement.
        field_updates (dict[str, str]): The engagement fields to update.
        account_id (Optional[str]): Salesforce Account ID to associate with the Engagement.
        contact_id (Optional[str]): Salesforce Contact ID to associate with the Engagement.

    Returns:
        Optional[str]: Updated Engagement ID or None if the operation failed.
    """
    engagement_id = None
    try:
        engagement = get_engagement_by_service_id(session, str(service.id))

        # Existing Engagement, update the stage name
        if engagement:
            result = session.Opportunity.update(
                engagement.get("Id"),
                engagement_maxlengths(field_updates),
                headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
            )
            is_updated = parse_result(result, f"Salesforce Engagement update '{service}' with '{field_updates}'")
            engagement_id = engagement.get("Id") if is_updated else None
        # Create the Engagement.  This handles Notify services that were created before Salesforce was added.
        else:
            engagement_id = create(session, service, field_updates, account_id, contact_id)

    except Exception as ex:
        current_app.logger.error(f"SF_ERR Salesforce Engagement update failed: {ex}")
    return engagement_id


def contact_role_add(session: Salesforce, service: Service, account_id: Optional[str], contact_id: Optional[str]) -> None:
    """Adds an Engagement ContactRole based on the provided Notify service and Contact.  If the
    Engagement does not exist, it is created.

    Args:
        session (Salesforce): Salesforce session to perform the operation.
        service (Service): The service's details for the engagement.
        account_id (Optional[str]): Salesforce Account ID to associate with the Engagement.
        contact_id (Optional[str]): Salesforce Contact ID for the Engagement's ContactRole.

    Returns:
        None
    """
    try:
        engagement = get_engagement_by_service_id(session, str(service.id))
        if engagement:
            result = session.OpportunityContactRole.create(
                {"ContactId": contact_id, "OpportunityId": engagement.get("Id")},
                headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
            )
            parse_result(result, f"Salesforce ContactRole add for {contact_id} with '{service.id}'")
        else:
            create(session, service, {}, account_id, contact_id)  # This implicitly creates the ContactRole
    except Exception as ex:
        current_app.logger.error(f"SF_ERR Salesforce ContactRole add for {contact_id} with '{service.id}' failed: {ex}")


def contact_role_delete(session: Salesforce, service: Service, account_id: Optional[str], contact_id: Optional[str]) -> None:
    """Deletes an Engagement ContactRole based on the provided Notify service and Salesforce Contact.
    If the Engagement does not exist, it is created.

    Args:
        session (Salesforce): Salesforce session to perform the operation.
        service (Service): The service's details for the engagement.
        account_id (Optional[str]): Salesforce Account ID to associate with the Engagement.
        contact_id (Optional[str]): Salesforce Contact ID to remove as a ContactRole.

    Returns:
        None
    """
    try:
        result = {}
        engagement = get_engagement_by_service_id(session, str(service.id))
        engagement_id = engagement.get("Id") if engagement else create(session, service, {}, account_id, contact_id)
        engagement_contact_role = get_engagement_contact_role(session, engagement_id, contact_id)

        if engagement_contact_role:
            result = session.OpportunityContactRole.delete(engagement_contact_role.get("Id"))
            parse_result(result, f"Salesforce ContactRole delete for {contact_id} with '{service.id}'")
    except Exception as ex:
        current_app.logger.error(f"SF_ERR Salesforce ContactRole delete for {contact_id} with '{service.id}' failed: {ex}")


def get_engagement_by_service_id(session: Salesforce, service_id: str) -> Optional[dict[str, Any]]:
    """Retrieve a Salesforce Engagement by a Notify service ID

    Args:
        session (Salesforce): Salesforce session to perform the operation.
        service_id (str): Notify service ID

    Returns:
        Optional[dict[str, str]]: Salesforce Engagement details or None if can't be found
    """
    result = None
    if isinstance(service_id, str) and service_id.strip():
        query = f"SELECT Id, Name, ContactId, AccountId FROM Opportunity where CDS_Opportunity_Number__c = '{query_param_sanitize(service_id)}' LIMIT 1"
        result = query_one(session, query)
    return result


def get_engagement_contact_role(
    session: Salesforce, engagement_id: Optional[str], contact_id: Optional[str]
) -> Optional[dict[str, Any]]:
    """Retrieve a Salesforce Engagement ContactRole.

    Args:
        session (Salesforce): Salesforce session to perform the operation.
        engagement_id (str): Salesforce Engagement ID
        contact_id (str): Salesforce Contact ID

    Returns:
        Optional[dict[str, str]]: Salesforce Engagement ContactRole details or None if can't be found
    """
    result = None
    if isinstance(engagement_id, str) and engagement_id.strip() and isinstance(contact_id, str) and contact_id.strip():
        query = f"SELECT Id, OpportunityId, ContactId FROM OpportunityContactRole WHERE OpportunityId = '{query_param_sanitize(engagement_id)}' AND ContactId = '{query_param_sanitize(contact_id)}' LIMIT 1"
        result = query_one(session, query)
    return result


def engagement_maxlengths(fields: dict[str, str]) -> dict[str, str]:
    """Given a dictionary of Engagement fields to update, truncate the values to the maximum length allowed by Salesforce.

    Args:
        field_updates (dict[str, str]): Engagement fields to check

    Returns:
        dict[str, str]: Field updates with values truncated to the maximum length allowed by Salesforce
    """
    maxlengths = {
        "Name": 120,
    }
    for field_name, maxlength in maxlengths.items():
        if field_name in fields:
            fields[field_name] = fields[field_name][:maxlength]
    return fields
