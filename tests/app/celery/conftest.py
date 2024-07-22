import pytest


@pytest.fixture
def ga4_sample_payload():
    return {
        'notification_id': 'e774d2a6-4946-41b5-841a-7ac6a42d178b',
        'template_name': 'hi',
        'template_id': 'e774d2a6-4946-41b5-841a-7ac6a42d178b',
        'service_id': 'e774d2a6-4946-41b5-841a-7ac6a42d178b',
        'service_name': 'test',
        'client_id': 'vanotify',
        'name': 'email_open',
        'source': 'vanotify',
        'medium': 'email',
    }
