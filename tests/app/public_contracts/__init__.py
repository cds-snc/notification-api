import os
from urllib.parse import urljoin
from urllib.request import pathname2url

from flask import json
import jsonschema
from jsonschema import Draft4Validator


def return_json_from_response(response):
    return json.loads(response.get_data(as_text=True))


def validate_v0(json_to_validate, schema_filename):
    schema_dir = os.path.join(os.path.dirname(__file__), 'schemas', 'v0')
    uri = urljoin('file:', pathname2url(schema_dir) + "/")
    resolver = jsonschema.RefResolver(uri, None)
    with open(os.path.join(schema_dir, schema_filename)) as schema:
        jsonschema.validate(
            json_to_validate,
            json.load(schema),
            format_checker=jsonschema.FormatChecker(),
            resolver=resolver
        )


def validate(json_to_validate, schema):
    validator = Draft4Validator(schema)
    validator.validate(json_to_validate, schema)
