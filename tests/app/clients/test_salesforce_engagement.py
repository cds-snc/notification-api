import pytest

from app.clients.salesforce import salesforce_engagement
from app.clients.salesforce.salesforce_engagement import (
    create,
    get_engagement_by_service_id,
    update_stage,
)
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


def test_update_stage_existing(mocker, notify_api, service):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_get_engagement_by_service_id = mocker.patch.object(
            salesforce_engagement, "get_engagement_by_service_id", return_value={"Id": "42"}
        )
        mock_session.Opportunity.update.return_value = {"success": True, "Id": "42"}

        assert update_stage(mock_session, service, "potatoes", None, None) == "42"

        mock_session.Opportunity.update.assert_called_with(
            "42", {"StageName": "potatoes"}, headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"}
        )
        mock_get_engagement_by_service_id.assert_called_with(mock_session, "3")


def test_update_stage_new(mocker, notify_api, service):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_get_engagement_by_service_id = mocker.patch.object(
            salesforce_engagement, "get_engagement_by_service_id", return_value=None
        )
        mock_create = mocker.patch.object(salesforce_engagement, "create", return_value="42")

        assert update_stage(mock_session, service, "potatoes", "account_id", "contact_id") == "42"

        mock_get_engagement_by_service_id.assert_called_with(mock_session, "3")
        mock_create.assert_called_with(mock_session, service, "potatoes", "account_id", "contact_id")


def test_update_stage_failed(mocker, notify_api, service):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mocker.patch.object(salesforce_engagement, "get_engagement_by_service_id", return_value={"Id": "42"})
        mock_session.Opportunity.update.return_value = {"success": False}
        assert update_stage(mock_session, service, "potatoes", "account_id", "contact_id") is None


def test_get_engagement_by_service_id(mocker, notify_api):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_query_one = mocker.patch.object(salesforce_engagement, "query_one", return_value={"Id": "42"})

        assert get_engagement_by_service_id(mock_session, "2") == {"Id": "42"}
        mock_query_one.assert_called_with(
            mock_session, "SELECT Id, Name, ContactId, AccountId FROM Opportunity where CDS_Opportunity_Number__c = '2' LIMIT 1"
        )


def test_get_engagement_by_service_id_blank(mocker, notify_api):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        assert get_engagement_by_service_id(mock_session, None) is None
        assert get_engagement_by_service_id(mock_session, "") is None
        assert get_engagement_by_service_id(mock_session, "       ") is None
