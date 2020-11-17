import pytest

from app.clients.va_profile.va_profile_client import VAProfileClient

MOCK_VA_PROFILE_URL = 'http://mock.vaprofile.va.gov'


@pytest.fixture(scope='function')
def test_va_profile_client():
    test_va_profile_client = VAProfileClient()
    return test_va_profile_client


def test_get_email_returns_a_value(notify_api, test_va_profile_client):
    email = test_va_profile_client.get_email('12')
    assert email


def test_get_email_contact_vaprofile(rmock, test_va_profile_client):
    rmock.request(
        "GET",
        MOCK_VA_PROFILE_URL,
        json={"status": "success"},
        status_code=200)

    test_va_profile_client.get_email('12')
    assert rmock.called
    assert rmock.request_history[0].url == MOCK_VA_PROFILE_URL
