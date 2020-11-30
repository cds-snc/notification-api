import pytest
from app.va.mpi import MpiClient, UnsupportedIdentifierException
from app.va import IdentifierType
from app.models import RecipientIdentifier
from requests_mock import ANY
from tests.app.factories.recipient_idenfier import sample_recipient_identifier


mock_url = "https://foo.bar"

@pytest.fixture
def mpi_client():
    mpi_client = MpiClient()
    mpi_client.init_app(url=mock_url)
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

    def test_should_throw_error_when_ivalid_type(self, mpi_client):
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

    def test_should_return_va_profile_id(self, mpi_client, rmock, sample_notification_model_with_organization):
        notification = sample_notification_model_with_organization
        notification.recipient_identifiers.set(sample_recipient_identifier())
        expected_va_profile_id = "1234"

        rmock.request(
            "GET",
            ANY,
            json={"vaprofileId": expected_va_profile_id},
            status_code=200
        )

        actual_va_profile_id = mpi_client.get_va_profile_id(notification)

        assert actual_va_profile_id == expected_va_profile_id

        assert rmock.called
        expected_url = mock_url
        assert rmock.request_history[0].url == expected_url
