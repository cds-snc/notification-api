import pytest

from app.va import is_fhir_format


@pytest.mark.parametrize(
    "identifier_value, expected_is_fhir_format",
    [
        ("123", False),
        ("12323423^BRLS^200^USDVA", True)
    ]
)
def test_is_fhir_format(identifier_value, expected_is_fhir_format):
    assert is_fhir_format(identifier_value) == expected_is_fhir_format
