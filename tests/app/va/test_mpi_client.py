import pytest
from app.va.mpi import MpiClient, UnsupportedIdentifierException
from app.va import IdentifierType
from app.models import RecipientIdentifier


@pytest.fixture
def mpi_client():
    return MpiClient()


class TestTransformToFhirFormat:
    @pytest.mark.parametrize("id_type, id_value, expected", [
        (IdentifierType.ICN.value, "1008533405V377263", "1008533405V377263^NI^200M^USVHA"),
        (IdentifierType.PID.value, "123456", "123456^PI^200CORP^USVBA"),
        (IdentifierType.VA_PROFILE_ID.value, "301", "301^PI^200VETS^USDVA"),
    ])
    def test_should_transform_recipient_identifier_to_mpi_acceptable_format(self, mpi_client, id_type, id_value, expected):
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
