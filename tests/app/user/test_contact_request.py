from typing import Any, Dict

import pytest
from notifications_utils.recipients import InvalidEmailError

from app.user.contact_request import ContactRequest


def test_contact_info():
    mock_dict = {
        "email_address": "test@email.com",
        "tags": ["test1", "test2"],
        "name": "test_name",
        "department_org_name": "org",
        "program_service_name": "service",
        "intended_recipients": "recipients",
        "main_use_case": "usecase",
        "main_use_case_details": "details",
        "friendly_support_type": "f_support_type",
        "language": "en",
        "support_type": "support_type",
        "message": "message",
        "user_profile": "user_profile",
        "service_name": "service_name",
        "service_id": "service_id",
        "service_url": "service_url",
        "notification_types": "notification_types",
    }
    contact = ContactRequest(**mock_dict)
    assert mock_dict["email_address"] == contact.email_address
    assert mock_dict["name"] == contact.name
    assert mock_dict["department_org_name"] == contact.department_org_name
    assert mock_dict["program_service_name"] == contact.program_service_name
    assert mock_dict["intended_recipients"] == contact.intended_recipients
    assert mock_dict["main_use_case"] == contact.main_use_case
    assert mock_dict["main_use_case_details"] == contact.main_use_case_details
    assert mock_dict["friendly_support_type"] == contact.friendly_support_type
    assert mock_dict["language"] == contact.language
    assert mock_dict["support_type"] == contact.support_type
    assert mock_dict["message"] == contact.message
    assert mock_dict["user_profile"] == contact.user_profile
    assert mock_dict["service_name"] == contact.service_name
    assert mock_dict["service_id"] == contact.service_id
    assert mock_dict["service_url"] == contact.service_url
    assert mock_dict["notification_types"] == contact.notification_types


def test_contact_info_defaults():
    mock_dict = {
        "email_address": "test@email.com",
    }
    contact = ContactRequest(**mock_dict)
    assert mock_dict["email_address"] == contact.email_address
    assert contact.language == "en"
    assert contact.friendly_support_type == "Support Request"
    assert contact.name == ""
    assert contact.department_org_name == ""
    assert contact.program_service_name == ""
    assert contact.intended_recipients == ""
    assert contact.main_use_case == ""
    assert contact.main_use_case_details == ""
    assert contact.support_type == ""
    assert contact.message == ""
    assert contact.user_profile == ""
    assert contact.service_name == ""
    assert contact.service_id == ""
    assert contact.service_url == ""
    assert contact.notification_types == ""


@pytest.mark.parametrize(
    "mock_dict",
    [dict(), {"email_address": ""}, {"email_address": "this_is_not_an_email_address"}],
)
def test_contact_info_invalid_email(mock_dict: Dict[str, Any]):
    with pytest.raises((TypeError, AssertionError, InvalidEmailError)):
        ContactRequest(**mock_dict)


def test_contact_info_additional_fields():
    mock_dict_new_field = {
        "email_address": "test@email.com",
        "invalid_additional_field": "new_field",
    }

    with pytest.raises(TypeError):
        ContactRequest(**mock_dict_new_field)


def test_contact_info_sanitize_input():
    mock_dict_sanitize = {
        "email_address": "test@email.com",
        "name": "<script>alert('hello')</script>",
    }
    contact = ContactRequest(**mock_dict_sanitize)
    assert contact.name == "&lt;script&gt;alert(&#39;hello&#39;)&lt;/script&gt;"
