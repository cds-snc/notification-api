import pytest

from app.va import is_fhir_format


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
def test_is_fhir_format(identifier_value, expected_is_fhir_format):
    assert is_fhir_format(identifier_value) == expected_is_fhir_format
