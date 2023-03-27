import pytest

from app.clients.salesforce import salesforce_engagement
from app.clients.salesforce.salesforce_engagement import create
from app.models import Service


@pytest.fixture
def service():
    return Service(
        **{
            "id": 3,
            "name": "The Fellowship",
        }
    )


def test_create(mocker, notify_api, service):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_session.Opportunity.create.return_value = {"success": True, "id": "9"}
        mock_datetime = mocker.patch.object(salesforce_engagement, "datetime")
        mock_datetime.today.return_value.strftime.return_value = "1970-01-01"
        notify_api.config["SALESFORCE_ENGAGEMENT_RECORD_TYPE"] = "hobbitsis"
        notify_api.config["SALESFORCE_ENGAGEMENT_STANDARD_PRICEBOOK_ID"] = "the ring"
        notify_api.config["SALESFORCE_ENGAGEMENT_PRODUCT_ID"] = "my precious"

        assert create(mock_session, service, "lambas", "123", "456") == "9"

        mock_session.Opportunity.create.assert_called_with(
            {
                "Name": "The Fellowship",
                "AccountId": "123",
                "ContactId": "456",
                "CDS_Opportunity_Number__c": "3",
                "StageName": "lambas",
                "CloseDate": "1970-01-01",
                "RecordTypeId": "hobbitsis",
                "Type": salesforce_engagement.ENGAGEMENT_TYPE,
                "CDS_Lead_Team__c": salesforce_engagement.ENGAGEMENT_TEAM,
                "Product_to_Add__c": salesforce_engagement.ENGAGEMENT_PRODUCT,
            },
            headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
        )

        mock_session.OpportunityLineItem.create.assert_called_with(
            {
                "OpportunityId": "9",
                "PricebookEntryId": "the ring",
                "Product2Id": "my precious",
                "Quantity": 1,
                "UnitPrice": 0,
            },
            headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
        )


def test_create_no_engagement_id(mocker, notify_api, service):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_session.Opportunity.create.return_value = {"success": False}
        assert create(mock_session, service, "lambas", "123", "456") is None
        mock_session.Opportunity.create.assert_called_once()
        mock_session.OpportunityLineItem.create.assert_not_called()


def test_create_no_engagement(mocker, notify_api, service):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        assert create(mock_session, service, "lambas", None, None) is None
        mock_session.Opportunity.create.assert_not_called()
        mock_session.OpportunityLineItem.create.assert_not_called()
