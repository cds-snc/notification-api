import pytest

from app.models import RecipientIdentifier
from app.va.identifier import is_fhir_format, IdentifierType, transform_to_fhir_format
from app.va.mpi import UnsupportedIdentifierException


class TestIsFhirFormat:
    @pytest.mark.parametrize(
        "identifier_value, expected_is_fhir_format",
        [
            ("12323423^BRLS^200^USDVA", True),
            ("12323423", False),
            ("123456^PI^200CORP^USVBA", True),
            ("12345^PI^200CRNR^USVHA^A", True),
            ("1008533405V377263^NI^200M^USVHA", True),
            ("1008533405V377263", False),
        ]
    )
    def test_is_fhir_format(self, identifier_value, expected_is_fhir_format):
        assert is_fhir_format(identifier_value) == expected_is_fhir_format


class TestTransformToFhirFormat:
    @pytest.mark.parametrize("id_type, id_value, expected_fhir_format", [
        (IdentifierType.ICN, "1008533405V377263", "1008533405V377263^NI^200M^USVHA"),
        (IdentifierType.PID, "123456", "123456^PI^200CORP^USVBA"),
        (IdentifierType.VA_PROFILE_ID, "301", "301^PI^200VETS^USDVA"),
        (IdentifierType.BIRLSID, "789123", "789123^PI^200BRLS^USVBA")
    ])
    def test_should_transform_recipient_identifier_to_mpi_acceptable_format(
            self,
            id_type,
            id_value,
            expected_fhir_format
    ):
        recipient_identifier = RecipientIdentifier(
            notification_id="123456",
            id_type=id_type.value,
            id_value=id_value
        )
        actual_fhir_format = transform_to_fhir_format(recipient_identifier)

        assert actual_fhir_format == expected_fhir_format

    def test_should_throw_error_when_invalid_type(self):
        recipient_identifier = RecipientIdentifier(
            notification_id="123456",
            id_type="unknown_type",
            id_value="123"
        )
        with pytest.raises(UnsupportedIdentifierException) as e:
            transform_to_fhir_format(recipient_identifier)
        assert "No identifier of type" in str(e.value)

    def test_should_throw_error_when_no_mapping_for_type(self, mocker):
        mock_identifier = mocker.Mock(IdentifierType)
        mock_identifier.name = "MOCKED_IDENTIFIER"
        mock_identifier.value = "mocked_value"
        mocker.patch("app.va.identifier.IdentifierType", return_value=mock_identifier)
        recipient_identifier = RecipientIdentifier(
            notification_id="123456",
            id_type=mock_identifier.name,
            id_value=mock_identifier.value
        )
        with pytest.raises(UnsupportedIdentifierException) as e:
            transform_to_fhir_format(recipient_identifier)
        assert "No mapping for identifier" in str(e.value)
