import pytest


@pytest.fixture
def ga4_request_data():
    """
    This is valid data.
    """

    return {
        'campaign': 'hi',
        'campaign_id': 'e774d2a6-4946-41b5-841a-7ac6a42d178b',
        'name': 'email_open',
        'source': 'vanotify',
        'medium': 'email',
        'content': 'test/e774d2a6-4946-41b5-841a-7ac6a42d178b/e774d2a6-4946-41b5-841a-7ac6a42d178b',
    }
