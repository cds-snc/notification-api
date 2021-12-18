import pytest
from base64 import b64encode
from requests_mock import ANY
from uuid import uuid4
from app.va.identifier import IdentifierType
from app.va.vetext import VETextClient
from tests.app.factories.recipient_idenfier import sample_recipient_identifier


MOCK_VETEXT_URL = 'http://mock.vetext.va.gov'
MOCK_USER = 'some-user'
MOCK_PASSWORD = 'some-password'


@pytest.fixture(scope='function')
def test_vetext_client(mocker):
    test_vetext_client = VETextClient()
    test_vetext_client.init_app(
        MOCK_VETEXT_URL,
        {'username': MOCK_USER, 'password': MOCK_PASSWORD}
    )
    return test_vetext_client


def test_send_push_notification_correct_request(rmock, test_vetext_client):
    response = {
        "success": True,
        "statusCode": 200
    }
    rmock.post(ANY, json=response, status_code=200)

    mobile_app_id = "ABCD"
    template_id = str(uuid4())
    icn = sample_recipient_identifier(IdentifierType.ICN)
    personalsation = {
        "foo": "bar"
    }

    test_vetext_client.send_push_notification(
        mobile_app_id,
        template_id,
        icn.id_value,
        personalsation)

    assert rmock.called

    expected_url = f"{MOCK_VETEXT_URL}/mobile/push/send"
    request = rmock.request_history[0]
    assert request.url == expected_url
    assert request.json() == {
        'appSid': mobile_app_id,
        'templateSid': template_id,
        'icn': icn.id_value,
        'personalization': personalsation
    }
    expected_auth = 'Basic ' + b64encode(bytes(f"{MOCK_USER}:{MOCK_PASSWORD}", 'utf-8')).decode("ascii")
    assert request.headers.get('Authorization') == expected_auth
