from app.clients.salesforce import salesforce_account
from app.clients.salesforce.salesforce_account import (
    ORG_NOTES_ORG_NAME_INDEX,
    ORG_NOTES_OTHER_NAME_INDEX,
    get_account_id_from_name,
    get_org_name_from_notes,
)


def test_get_org_name_from_notes():
    assert get_org_name_from_notes("Account Name 1 > Service Name", ORG_NOTES_ORG_NAME_INDEX) == "Account Name 1"
    assert get_org_name_from_notes("Account Name 2 > Another service Name") == "Account Name 2"
    assert get_org_name_from_notes("Account Name 3 > Some service", ORG_NOTES_OTHER_NAME_INDEX) == "Some service"
    assert get_org_name_from_notes("Account Name 4 > Service Name > Team Name", 2) == "Team Name"
    assert get_org_name_from_notes(None) is None
    assert get_org_name_from_notes(">") == ""


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


def test_get_account_id_from_name_blank(mocker, notify_api):
    mock_session = mocker.MagicMock()
    with notify_api.app_context():
        assert get_account_id_from_name(mock_session, None, "generic_account_id") == "generic_account_id"
        assert get_account_id_from_name(mock_session, "", "generic_account_id") == "generic_account_id"
        assert get_account_id_from_name(mock_session, "     ", "generic_account_id") == "generic_account_id"
