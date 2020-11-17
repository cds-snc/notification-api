import pytest

from app.clients.va_profile.va_profile_client import VAProfileClient

MOCK_VA_PROFILE_URL = 'http://mock.vaprofile.va.gov/'


@pytest.fixture(scope='function')
def test_va_profile_client():
    test_va_profile_client = VAProfileClient()
    test_va_profile_client.init_app(MOCK_VA_PROFILE_URL)

    return test_va_profile_client


def test_get_email_gets_from_correct_url(notify_api, rmock, test_va_profile_client):
    va_profile_id = '12'
    expected_url = f"{MOCK_VA_PROFILE_URL}/contact-information-hub/cuf/contact-information/v1/{va_profile_id}/emails"

    rmock.request(
        "GET",
        expected_url,
        json={"status": "success"},
        status_code=200
    )

    test_va_profile_client.get_email(va_profile_id)

    assert rmock.called
    assert rmock.request_history[0].url == expected_url
