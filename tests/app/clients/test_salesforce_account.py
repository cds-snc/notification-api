from app.clients.salesforce import salesforce_account
from app.clients.salesforce.salesforce_account import (
    get_account_id_from_name,
    get_account_name_from_org,
)


def test_get_account_name_from_org():
    assert get_account_name_from_org("Account Name 1 > Service Name") == "Account Name 1"
    assert get_account_name_from_org("Account Name 2") == "Account Name 2"
    assert get_account_name_from_org("Account Name 3 >") == "Account Name 3"
    assert get_account_name_from_org("Account Name 4 > Service Name > Team Name") == "Account Name 4"
    assert get_account_name_from_org(None) is None


def test_get_account_id_from_name(mocker, notify_api):
    mock_session = mocker.MagicMock()
    mock_query_one = mocker.patch.object(salesforce_account, "query_one", return_value={"Id": "account_id"})
    with notify_api.app_context():
        assert get_account_id_from_name(mock_session, "Account Name", "generic_account_id") == "account_id"
        mock_query_one.assert_called_with(
            mock_session,
            "SELECT Id FROM Account where Name = 'Account Name' OR CDS_AccountNameFrench__c = 'Account Name' LIMIT 1",
        )


def test_get_account_id_from_name_generic(mocker, notify_api):
    mock_session = mocker.MagicMock()
    mock_query_one = mocker.patch.object(salesforce_account, "query_one", return_value=None)
    with notify_api.app_context():
        assert get_account_id_from_name(mock_session, "l'account", "generic_account_id") == "generic_account_id"
        mock_query_one.assert_called_with(
            mock_session, "SELECT Id FROM Account where Name = 'l\\'account' OR CDS_AccountNameFrench__c = 'l\\'account' LIMIT 1"
        )
