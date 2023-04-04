import pytest

from app.clients.salesforce import salesforce_contact
from app.clients.salesforce.salesforce_contact import (
    create,
    get_contact_by_user_id,
    update,
)
from app.models import User


@pytest.fixture
def user():
    return User(
        **{
            "id": 2,
            "name": "Samwise Gamgee",
            "email_address": "samwise@fellowship.ca",
            "platform_admin": False,
        }
    )


def test_create(mocker, notify_api, user):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_session.Contact.create.return_value = {"success": True, "id": "42"}
        assert create(mock_session, user, {}) == "42"
        mock_session.Contact.create.assert_called_with(
            {
                "FirstName": "Samwise",
                "LastName": "Gamgee",
                "Title": "created by Notify API",
                "CDS_Contact_ID__c": "2",
                "Email": "samwise@fellowship.ca",
            },
            headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
        )


def test_create_custom(mocker, notify_api, user):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_session.Contact.create.return_value = {"success": True, "id": "42"}
        assert create(mock_session, user, {"AccountId": "Samwise", "Lambas": "Bread"}) == "42"
        mock_session.Contact.create.assert_called_with(
            {
                "FirstName": "Samwise",
                "LastName": "Gamgee",
                "Title": "created by Notify API",
                "CDS_Contact_ID__c": "2",
                "Email": "samwise@fellowship.ca",
                "AccountId": "Samwise",
                "Lambas": "Bread",
            },
            headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
        )


def test_create_one_name(mocker, notify_api):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_session.Contact.create.return_value = {"success": True, "id": "42"}
        mock_user = User(
            **{
                "id": 3,
                "name": "Gandalf",
                "email_address": "gandalf@fellowship.ca",
                "platform_admin": False,
            }
        )
        assert create(mock_session, mock_user, {}) == "42"
        mock_session.Contact.create.assert_called_with(
            {
                "FirstName": "",
                "LastName": "Gandalf",
                "Title": "created by Notify API",
                "CDS_Contact_ID__c": "3",
                "Email": "gandalf@fellowship.ca",
            },
            headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
        )


def test_create_failed(mocker, notify_api, user):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_session.Contact.create.return_value = {"success": False}
        assert create(mock_session, user, {}) is None


def test_create_exception(mocker, notify_api, user):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_session.Contact.create.side_effect = Exception()
        assert create(mock_session, user, {}) is None


def test_update_account_id_existing(mocker, notify_api, user):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_get_contact_by_user_id = mocker.patch.object(salesforce_contact, "get_contact_by_user_id", return_value={"Id": "42"})
        mock_session.Contact.update.return_value = {"success": True, "Id": "42"}

        assert update(mock_session, user, {"AccountId": "potatoes", "Foo": "Bar"}) == "42"

        mock_session.Contact.update.assert_called_with(
            "42", {"AccountId": "potatoes", "Foo": "Bar"}, headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"}
        )
        mock_get_contact_by_user_id.assert_called_with(mock_session, "2")


def test_update_account_id_new(mocker, notify_api, user):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_get_contact_by_user_id = mocker.patch.object(salesforce_contact, "get_contact_by_user_id", return_value=None)
        mock_create = mocker.patch.object(salesforce_contact, "create", return_value="42")

        assert update(mock_session, user, {"AccountId": "potatoes", "Bam": "Baz"}) == "42"

        mock_get_contact_by_user_id.assert_called_with(mock_session, "2")
        mock_create.assert_called_with(mock_session, user, {"AccountId": "potatoes", "Bam": "Baz"})


def test_get_contact_by_user_id(mocker, notify_api):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_query_one = mocker.patch.object(salesforce_contact, "query_one", return_value={"Id": "42"})

        assert get_contact_by_user_id(mock_session, "2") == {"Id": "42"}
        mock_query_one.assert_called_with(
            mock_session, "SELECT Id, FirstName, LastName, AccountId FROM Contact WHERE CDS_Contact_ID__c = '2' LIMIT 1"
        )


def test_get_contact_by_user_id_blank(mocker, notify_api):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        assert get_contact_by_user_id(mock_session, None) is None
        assert get_contact_by_user_id(mock_session, "") is None
        assert get_contact_by_user_id(mock_session, "       ") is None
