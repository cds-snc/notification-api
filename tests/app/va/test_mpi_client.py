import copy

import pytest
from app.va.mpi import MpiClient, UnsupportedIdentifierException
from app.va import IdentifierType
from app.models import RecipientIdentifier
from requests_mock import ANY
from requests.utils import quote

from app.va.mpi.mpi import IdentifierNotFound
from tests.app.factories.recipient_idenfier import sample_recipient_identifier

EXPECTED_VA_PROFILE_ID = "15963"

BASE_MPI_RESPONSE_WITH_NO_VA_PROFILE_ID = {
    "resourceType": "Patient",
    "id": "1008710501V455565",
    "birthDate": "2010-06-03",
    "name": [
        {
            "use": "official",
            "family": "MOOSE",
            "given": [
                "MINNIE"
            ]
        }
    ],
    "telecom": [
        {
            "system": "phone",
            "value": "(240)979-5003",
            "use": "home"
        }
    ],
    "identifier": [
        {
            "system": "urn:oid:2.16.840.1.113883.4.349",
            "value": "1008710501V455565^NI^200M^USVHA^P"
        },
        {
            "system": "urn:oid:2.16.840.1.113883.4.349",
            "value": "32315716^PI^200CORP^USVBA^A"
        },
        {
            "system": "urn:oid:2.16.840.1.113883.4.349",
            "value": "15962^PI^200VETS^USDVA^H"
        },
        {
            "system": "urn:oid:2.16.840.1.113883.4.349",
            "value": "418418001^PI^200BRLS^USVBA^A"
        },
        {
            "system": "urn:oid:2.16.840.1.113883.4.349",
            "value": "418418001^AN^200CORP^USVBA^"
        },
        {
            "system": "http://hl7.org/fhir/sid/us-ssn",
            "value": "500333153"
        }
    ]
}


def response_with_one_active_va_profile_id():
    resp = copy.deepcopy(BASE_MPI_RESPONSE_WITH_NO_VA_PROFILE_ID)
    resp["identifier"].append({
        "system": "urn:oid:2.16.840.1.113883.4.349",
        "value": f"{EXPECTED_VA_PROFILE_ID}^PI^200VETS^USDVA^A"
    })
    return resp


def response_with_two_active_va_profile_ids():
    resp = response_with_one_active_va_profile_id()
    resp["identifier"].append({
        "system": "urn:oid:2.16.840.1.113883.4.349",
        "value": "15964^PI^200VETS^USDVA^A"
    })
    return resp


@pytest.fixture
def mpi_client():
    url = 'https://foo.bar'
    mock_ssl_key_path = 'some_key.pem'
    mock_ssl_cert_path = 'some_cert.pem'

    mpi_client = MpiClient()
    mpi_client.init_app(
        url,
        mock_ssl_cert_path,
        mock_ssl_key_path
    )
    return mpi_client


class TestTransformToFhirFormat:
    @pytest.mark.parametrize("id_type, id_value, expected", [
        (IdentifierType.ICN.value, "1008533405V377263", "1008533405V377263^NI^200M^USVHA"),
        (IdentifierType.PID.value, "123456", "123456^PI^200CORP^USVBA"),
        (IdentifierType.VA_PROFILE_ID.value, "301", "301^PI^200VETS^USDVA"),
    ])
    def test_should_transform_recipient_identifier_to_mpi_acceptable_format(self, mpi_client,
                                                                            id_type, id_value, expected):
        recipient_identifier = RecipientIdentifier(
            notification_id="123456",
            id_type=id_type,
            id_value=id_value
        )
        actual_fhir_format = mpi_client.transform_to_fhir_format(recipient_identifier)

        assert actual_fhir_format == expected

    def test_should_throw_error_when_invalid_type(self, mpi_client):
        recipient_identifier = RecipientIdentifier(
            notification_id="123456",
            id_type="unknown_type",
            id_value="123"
        )
        with pytest.raises(UnsupportedIdentifierException) as e:
            mpi_client.transform_to_fhir_format(recipient_identifier)
        assert "No identifier of type" in str(e.value)

    def test_should_throw_error_when_no_transformation(self, mpi_client, mocker):
        mock_identifier = mocker.Mock(IdentifierType)
        mock_identifier.name = "MOCKED_IDENTIFIER"
        mock_identifier.value = "mocked_value"
        mocker.patch("app.va.mpi.mpi.IdentifierType", return_value=mock_identifier)
        recipient_identifier = RecipientIdentifier(
            notification_id="123456",
            id_type=mock_identifier.name,
            id_value=mock_identifier.value
        )
        with pytest.raises(UnsupportedIdentifierException) as e:
            mpi_client.transform_to_fhir_format(recipient_identifier)
        assert "No mapping for identifier" in str(e.value)


class TestGetVaProfileId:

    @pytest.mark.parametrize("recipient_identifiers", [
        None,
        [sample_recipient_identifier(IdentifierType.ICN), sample_recipient_identifier(IdentifierType.PID)]
    ])
    def test_should_raise_exception_if_not_exactly_one_identifier(self,
                                                                  mpi_client,
                                                                  sample_notification_model_with_organization,
                                                                  recipient_identifiers):
        notification = sample_notification_model_with_organization
        if recipient_identifiers:
            for identifier in recipient_identifiers:
                notification.recipient_identifiers.set(identifier)
        with pytest.raises(ValueError) as e:
            mpi_client.get_va_profile_id(notification)
        assert "Unexpected number of recipient_identifiers" in str(e.value)

    def test_should_make_request_to_mpi_and_return_va_profile_id(
        self, mpi_client, rmock, sample_notification_model_with_organization
    ):
        notification = sample_notification_model_with_organization
        recipient_identifier = sample_recipient_identifier()
        notification.recipient_identifiers.set(recipient_identifier)

        rmock.request(
            "GET",
            ANY,
            json=response_with_one_active_va_profile_id(),
            status_code=200
        )

        expected_url = (f"{mpi_client.base_url}/psim_webservice/fhir/Patient/"
                        f"{quote(mpi_client.transform_to_fhir_format(recipient_identifier))}"
                        f"?-sender={MpiClient.SYSTEM_IDENTIFIER}")

        actual_va_profile_id = mpi_client.get_va_profile_id(notification)

        assert rmock.called
        assert rmock.request_history[0].url == expected_url

        assert actual_va_profile_id == EXPECTED_VA_PROFILE_ID

    def test_should_make_request_to_mpi_and_return_first_active_va_profile_id(
        self, mpi_client, rmock, sample_notification_model_with_organization
    ):
        notification = sample_notification_model_with_organization
        recipient_identifier = sample_recipient_identifier()
        notification.recipient_identifiers.set(recipient_identifier)

        rmock.request(
            "GET",
            ANY,
            json=response_with_two_active_va_profile_ids(),
            status_code=200
        )

        actual_va_profile_id = mpi_client.get_va_profile_id(notification)

        assert actual_va_profile_id == EXPECTED_VA_PROFILE_ID

    def test_should_throw_error_when_no_active_va_profile_id(
            self, mpi_client, rmock, sample_notification_model_with_organization
    ):
        notification = sample_notification_model_with_organization
        recipient_identifier = sample_recipient_identifier()
        notification.recipient_identifiers.set(recipient_identifier)

        rmock.request(
            "GET",
            ANY,
            json=BASE_MPI_RESPONSE_WITH_NO_VA_PROFILE_ID,
            status_code=200
        )

        with pytest.raises(IdentifierNotFound):
            mpi_client.get_va_profile_id(notification)
