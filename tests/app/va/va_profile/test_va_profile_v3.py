import json
import pytest


from app.va.va_profile import VAProfileClient
from app.models import RecipientIdentifier
from app.va.identifier import IdentifierType, transform_to_fhir_format, OIDS


MOCK_VA_PROFILE_URL = 'http://mock.vaprofile.va.gov'


@pytest.fixture(scope='function')
def mock_va_profile_client(mocker, notify_api):
    with notify_api.app_context():
        mock_logger = mocker.Mock()
        mock_ssl_key_path = 'some_key.pem'
        mock_ssl_cert_path = 'some_cert.pem'
        mock_statsd_client = mocker.Mock()
        mock_va_profile_token = mocker.Mock()

        client = VAProfileClient()
        client.init_app(
            logger=mock_logger,
            va_profile_url=MOCK_VA_PROFILE_URL,
            ssl_cert_path=mock_ssl_cert_path,
            ssl_key_path=mock_ssl_key_path,
            va_profile_token=mock_va_profile_token,
            statsd_client=mock_statsd_client,
        )

        return client


@pytest.fixture(scope='module')
def mock_response():
    with open('tests/app/va/va_profile/mock_response.json', 'r') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def recipient_identifier():
    return RecipientIdentifier(notification_id='123456', id_type=IdentifierType.VA_PROFILE_ID, id_value='1234')


@pytest.fixture(scope='module')
def id_with_aaid(recipient_identifier):
    return transform_to_fhir_format(recipient_identifier)


@pytest.fixture(scope='module')
def oid(recipient_identifier):
    return OIDS.get(recipient_identifier.id_type)


def test_ut_get_email_from_profile_v3_calls_endpoint_and_returns_email_address(
    rmock, mock_va_profile_client, mock_response, recipient_identifier, id_with_aaid, oid
):
    url = f'{MOCK_VA_PROFILE_URL}/profile-service/profile/v3/{oid}/{id_with_aaid}'
    rmock.post(url, json=mock_response, status_code=200)

    email = mock_va_profile_client.get_email_from_profile_v3(recipient_identifier)

    assert email == mock_response['profile']['contactInformation']['emails'][0]['emailAddressText']
    assert rmock.called


def test_ut_get_telephone_from_profile_v3_calls_endpoint_and_returns_phone_number(
    rmock, mock_va_profile_client, mock_response, recipient_identifier, id_with_aaid, oid
):
    url = f'{MOCK_VA_PROFILE_URL}/profile-service/profile/v3/{oid}/{id_with_aaid}'
    rmock.post(url, json=mock_response, status_code=200)

    telephone = mock_va_profile_client.get_telephone_from_profile_v3(recipient_identifier)

    assert telephone is not None
    assert rmock.called


@pytest.mark.parametrize('expected', [True, False])
def test_ut_get_is_communication_allowed_v3_returns_whether_permissions_granted_for_sms_communication(
    rmock, mock_va_profile_client, mock_response, recipient_identifier, id_with_aaid, oid, expected
):
    mock_response['profile']['communicationPermissions'][0]['allowed'] = expected
    url = f'{MOCK_VA_PROFILE_URL}/profile-service/profile/v3/{oid}/{id_with_aaid}'
    rmock.post(url, json=mock_response, status_code=200)

    perm = mock_response['profile']['communicationPermissions'][0]
    allowed = mock_va_profile_client.get_is_communication_allowed_v3(
        recipient_identifier, perm['communicationItemId'], 'bar', 'sms'
    )

    assert allowed is expected
    assert rmock.called


@pytest.mark.parametrize('expected', [True, False])
def test_ut_get_is_communication_allowed_v3_returns_whether_permissions_granted_for_email_communication(
    rmock, mock_va_profile_client, mock_response, recipient_identifier, id_with_aaid, oid, expected
):
    mock_response['profile']['communicationPermissions'][1]['allowed'] = expected
    url = f'{MOCK_VA_PROFILE_URL}/profile-service/profile/v3/{oid}/{id_with_aaid}'
    rmock.post(url, json=mock_response, status_code=200)

    perm = mock_response['profile']['communicationPermissions'][1]
    allowed = mock_va_profile_client.get_is_communication_allowed_v3(
        recipient_identifier, perm['communicationItemId'], 'bar', 'email'
    )

    assert allowed is expected
    assert rmock.called
