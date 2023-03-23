import pytest

from app.clients.salesforce.salesforce_contact import create
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
        assert create(mock_session, user, "potatoes") == (True, "42")
        mock_session.Contact.create.assert_called_with(
            {
                "FirstName": "Samwise",
                "LastName": "Gamgee",
                "Title": "created by Notify API",
                "CDS_Contact_ID__c": "2",
                "Email": "samwise@fellowship.ca",
                "AccountId": "potatoes",
            },
            headers={"Sforce-Duplicate-Rule-Header": "allowSave=true"},
        )


def test_create_failed(mocker, notify_api, user):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_session.Contact.create.return_value = {"success": False}
        assert create(mock_session, user, None) == (False, None)


def test_create_exception(mocker, notify_api, user):
    with notify_api.app_context():
        mock_session = mocker.MagicMock()
        mock_session.Contact.create.side_effect = Exception()
        assert create(mock_session, user, None) == (False, None)
