"""Test the schemas for /ga4."""

import pytest
from app.googleanalytics.ga4_schemas import ga4_request_schema
from app.googleanalytics.ga4 import ga4_request_validator
from jsonschema import ValidationError


def test_ga4_request_schema():
    """
    Test that the schema declared in app/googleanalytics/ga4_schemas.py is valid
    with the validator declared in app/googleanalytics/ga4.py.
    """

    # This should not raise SchemaError.
    ga4_request_validator.check_schema(ga4_request_schema)


def test_valid_ga4_request_schema_data(ga4_request_data):
    ga4_request_validator.validate(ga4_request_data)


def test_ga4_request_schema_required_properties(ga4_request_data):
    """
    All of the properties in ga4_request_data are required.
    """

    for key in ga4_request_data:
        modified_data = ga4_request_data.copy()
        del modified_data[key]

        with pytest.raises(ValidationError):
            ga4_request_validator.validate(modified_data)


def test_ga4_request_schema_additional_properties(ga4_request_data):
    """
    The data may not include any additional properties.
    """

    ga4_request_data['additonal'] = ''

    with pytest.raises(ValidationError):
        ga4_request_validator.validate(ga4_request_data)


def test_ga4_request_schema_campaign_id_uuid(ga4_request_data):
    """
    The value of campaign_id must be a UUID.
    """

    ga4_request_data['campaign_id'] = 'not a uuid'

    with pytest.raises(ValidationError):
        ga4_request_validator.validate(ga4_request_data)


@pytest.mark.parametrize(
    'content',
    (
        '',
        'something',
        'test/foo/bar',
        'test/e774d2a6-4946-41b5-841a-7ac6a42d178b/bar',
        'test/foo/e774d2a6-4946-41b5-841a-7ac6a42d178b',
        'test/e774d2a6-4946-41b5-841a-7ac6a42d178b/e774d2a6-4946-41b5-841a-7ac6a42d178b/something',
    ),
)
def test_ga4_request_schema_content(ga4_request_data, content):
    """
    The value of the content property must be '{str}/{uuid}/{uuid}.
    """

    ga4_request_data['content'] = content

    with pytest.raises(ValidationError):
        ga4_request_validator.validate(ga4_request_data)
