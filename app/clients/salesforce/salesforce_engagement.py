from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from flask import current_app
from simple_salesforce import Salesforce

from .salesforce_utils import parse_result

if TYPE_CHECKING:
    from app.models import Service

ENGAGEMENT_PRODUCT = "GC Notify"
ENGAGEMENT_TEAM = "Platform"
ENGAGEMENT_TYPE = "New Business"
ENGAGEMENT_STAGE_ACTIVATION = "Activation"
ENGAGEMENT_STAGE_LIVE = "Live"
ENGAGEMENT_STAGE_TRIAL = "Trial Account"


def create(
    session: Salesforce, service: Service, stage_name: str, account_id: Optional[str], contact_id: Optional[str]
) -> Optional[str]:
    """Create a Salesforce Engagement for the given Notify service

    Args:
        session (Salesforce): Salesforce session to perform the operation.
        service (Service): The service's details for the engagement.
        stage_name (str): The service's stage name.
        account_id (Optional[str]): Salesforce Account ID to associate with the Engagement.
        contact_id (Optional[str]): Salesforce Contact ID to associate with the Engagement.

    Returns:
       Optional[str]: Newly created Engagement ID or None if the operation failed.
    """
    engagement_id = None
    try:
        if account_id and contact_id:
            result = session.Opportunity.create(
                {
                    "Name": service.name,
                    "AccountId": account_id,
                    "ContactId": contact_id,
                    "CDS_Opportunity_Number__c": str(service.id),
                    "StageName": stage_name,
                    "CloseDate": datetime.today().strftime("%Y-%m-%d"),
                    "RecordTypeId": current_app.config["SALESFORCE_ENGAGEMENT_RECORD_TYPE"],
                    "Type": ENGAGEMENT_TYPE,
                    "CDS_Lead_Team__c": ENGAGEMENT_TEAM,
                    "Product_to_Add__c": ENGAGEMENT_PRODUCT,
                },
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
                f"Salesforce Engagement create failed: missing Account ID '{account_id}' or Contact ID '{contact_id}' for service ID {service.id}"
            )
    except Exception as ex:
        current_app.logger.error(f"Salesforce Engagement create failed: {ex}")
    return engagement_id
