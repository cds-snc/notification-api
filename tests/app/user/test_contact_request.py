from app.user.contact_request import ContactRequest
from notifications_utils.recipients import InvalidEmailError


def test_contact_info():
    mock_dict = {
        'email_address': 'test@email.com',
        'tags': ['test1', 'test2'],
        'name': 'test_name',
        'department_org_name': 'org',
        'program_service_name': 'service',
        'intended_recipients': 'recipients',
        'main_use_case': 'usecase',
        'main_use_case_details': 'details',
        'friendly_support_type': 'f_support_type',
        'language': 'en',
        'support_type': 'support_type',
        'message': 'message',
        'user_profile': 'user_profile'
    }
    contact = ContactRequest(**mock_dict)
    assert mock_dict['email_address'] == contact.email_address
    assert mock_dict['name'] == contact.name
    assert mock_dict['department_org_name'] == contact.department_org_name
    assert mock_dict['program_service_name'] == contact.program_service_name
    assert mock_dict['intended_recipients'] == contact.intended_recipients
    assert mock_dict['main_use_case'] == contact.main_use_case
    assert mock_dict['main_use_case_details'] == contact.main_use_case_details
    assert mock_dict['friendly_support_type'] == contact.friendly_support_type
    assert mock_dict['language'] == contact.language
    assert mock_dict['support_type'] == contact.support_type
    assert mock_dict['message'] == contact.message
    assert mock_dict['user_profile'] == contact.user_profile


def test_contact_info_defaults():
    mock_dict = {
        'email_address': 'test@email.com',
    }
    contact = ContactRequest(**mock_dict)
    empty_str = ''
    assert mock_dict['email_address'] == contact.email_address
    assert contact.language == 'en'
    assert contact.support_type == 'Support Request'
    assert contact.name == empty_str
    assert contact.department_org_name == empty_str
    assert contact.program_service_name == empty_str
    assert contact.intended_recipients == empty_str
    assert contact.main_use_case == empty_str
    assert contact.main_use_case_details == empty_str
    assert contact.friendly_support_type == empty_str
    assert contact.message == empty_str
    assert contact.user_profile == empty_str


def test_contact_info_invalid_email():

    mock_dict_empty = dict()
    mock_dict_email_empty = {'email_address': ''}
    mock_dict_malformed_email = {'email_address': 'this_is_not_an_email_address'}

    try:
        contact = ContactRequest(**mock_dict_empty)
    except Exception as e:
        assert isinstance(e, TypeError)

    try:
        contact = ContactRequest(**mock_dict_email_empty)
    except Exception as e:
        assert isinstance(e, AssertionError)

    try:
        contact = ContactRequest(**mock_dict_malformed_email)
    except Exception as e:
        assert isinstance(e, InvalidEmailError)


def test_contact_info_additional_fields():
    mock_dict_new_field = {
        'email_address': 'test@email.com',
        'invalid_additional_field': 'new_field'
    }

    try:
        contact = ContactRequest(**mock_dict_new_field)
    except Exception as e:
        assert isinstance(e, TypeError)


def test_contact_info_sanitize_input():
    mock_dict_sanitize = {
        'email_address': 'test@email.com',
        'name': "<script>alert('hello')</script>"
    }
    contact = ContactRequest(**mock_dict_sanitize)
    assert contact.name == '&lt;script&gt;alert(&#39;hello&#39;)&lt;/script&gt;'
