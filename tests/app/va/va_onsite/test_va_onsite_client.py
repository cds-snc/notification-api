import pytest
import re
import requests

from app.va.va_onsite import VAOnsiteClient

MOCK_VA_ONSITE_URL = 'http://mock.vaonsite.va.gov'


@pytest.fixture()
def test_va_onsite_client(mocker):
    mock_logger = mocker.Mock()
    # When using the ES256 algorithm for JWT generation you must use a real ES256 key
    #   and it must be in this format or you will get errors
    # This key is a dummy that was created for testing
    # Generate this type of key with openssl: https://notes.salrahman.com/generate-es256-es384-es512-private-keys/
    mock_secret_key = '-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIC9j+V0ZhWgB/KFFCiRhgVA+ZWBSjeVwtHToFDgeEi0HoAoGCCqGSM49\nAwEHoUQDQgAEDDDYZTvCx957Uj9AHrt/wRt+eThZqj0tjTyOkhaOJ1TTFVtgPMqG\nwnYZ/dBhHpmyafvss+L4/Hq/D1XXnVwq3A==\n-----END EC PRIVATE KEY-----'  # noqa: E501

    test_va_onsite_client = VAOnsiteClient()
    test_va_onsite_client.init_app(
        mock_logger,
        MOCK_VA_ONSITE_URL,
        mock_secret_key
    )

    return test_va_onsite_client


def test_post_onsite_notification_returns_200(rmock, test_va_onsite_client):
    resp = {
        'data':
        {
            'id': '1',
            'type': 'onsite_notifications',
            'attributes':
            {
                'template_id': 'some-templat-id',
                'va_profile_id': '1',
                'dismissed': False,
                'created_at': '2022-06-14T18:00:57.036Z',
                'updated_at': '2022-06-14T18:00:57.036Z'
            }
        }
    }

    rmock.post(f'{MOCK_VA_ONSITE_URL}/v0/onsite_notifications', json=resp, status_code=200)

    response = test_va_onsite_client.post_onsite_notification(
        {
            "template_id": "f9947b27-df3b-4b09-875c-7f76594d766d",
            "va_profile_id": "1"  # "505193" this is the example number from api docs
        })

    assert rmock.called

    assert response.status_code == requests.codes.ok

    response_json = response.json()
    assert response_json['data']['type'] == 'onsite_notifications'
    assert response_json['data']['attributes']['va_profile_id'] == '1'

    request = rmock.request_history[0]
    expected_url = f'{MOCK_VA_ONSITE_URL}/v0/onsite_notifications'
    assert request.url == expected_url

    # very basic JWT validation, it only makes sure it's in the correct format
    auth = request.headers.get('Authorization')
    regex = re.compile(r'Bearer ([\w-]+\.){2}[\w-]+')
    assert regex.match(auth)
