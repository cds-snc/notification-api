import json
import uuid

import pytest
from jsonschema import ValidationError

from app.schema_validation import validate
from app.service.service_callback_api_schema import (
    update_service_inbound_api_schema, update_service_callback_api_request_schema,
    create_service_callback_api_request_schema)


def test_service_inbound_api_schema_validates():
    under_test = {"url": "https://some_url.for_service",
                  "bearer_token": "something_ten_chars",
                  "updated_by_id": str(uuid.uuid4())
                  }

    validated = validate(under_test, update_service_inbound_api_schema)
    assert validated == under_test


@pytest.mark.parametrize("url", ["not a url", "https not a url", "http://valid.com"])
def test_service_inbound_api_schema_errors_for_url_not_valid_url(url):
    under_test = {"url": url,
                  "bearer_token": "something_ten_chars",
                  "updated_by_id": str(uuid.uuid4())
                  }

    with pytest.raises(ValidationError) as e:
        validate(under_test, update_service_inbound_api_schema)
    errors = json.loads(str(e.value)).get('errors')
    assert len(errors) == 1
    assert errors[0]['message'] == "url is not a valid https url"


def test_service_inbound_api_schema_bearer_token_under_ten_char():
    under_test = {"url": "https://some_url.for_service",
                  "bearer_token": "shorty",
                  "updated_by_id": str(uuid.uuid4())
                  }

    with pytest.raises(ValidationError) as e:
        validate(under_test, update_service_inbound_api_schema)
    errors = json.loads(str(e.value)).get('errors')
    assert len(errors) == 1
    assert errors[0]['message'] == "bearer_token shorty is too short"


def test_create_service_callback_api_schema_validate_succeeds():
    under_test = {
        "url": "https://some_url.for_service",
        "bearer_token": "something_ten_chars",
        "notification_statuses": ["failed"],
        "updated_by_id": str(uuid.uuid4())
    }

    validated = validate(under_test, create_service_callback_api_request_schema)
    assert validated == under_test


@pytest.mark.parametrize('key, value', [
    ("url", "https://some_url.for_service"),
    ("bearer_token", "something_ten_chars"),
    ("notification_statuses", ["failed"]),
    ("updated_by_id", "6ce466d0-fd6a-11e5-82f5-e0accb9d11a6"),
    (None, None)
])
def test_create_service_callback_api_schema_validate_fails_when_missing_properties(key, value):
    under_test = {key: value}

    with pytest.raises(ValidationError) as e:
        validate(under_test, create_service_callback_api_request_schema)

    errors = json.loads(str(e.value)).get('errors')
    assert len(errors) > 1
    for message in errors:
        assert message['error'] == 'ValidationError'
        assert 'is a required property' in message['message']


@pytest.mark.parametrize('key, wrong_key, value', [
    ("url", "urls", "https://some_url.for_service"),
    ("bearer_token", "bearers_token", "something_ten_chars"),
    ("notification_statuses", "notifications_statuses", ["failed"]),
    ("updated_by_id", "update_by_id", "6ce466d0-fd6a-11e5-82f5-e0accb9d11a6")
])
def test_create_service_callback_api_schema_validate_fails_with_misspelled_keys(key, wrong_key, value):
    under_test = {
        "url": "https://some_url.for_service",
        "bearer_token": "something_ten_chars",
        "notification_statuses": ["failed"],
        "updated_by_id": str(uuid.uuid4())
    }
    del under_test[key]
    under_test[wrong_key] = value

    with pytest.raises(ValidationError) as e:
        validate(under_test, create_service_callback_api_request_schema)

    errors = json.loads(str(e.value)).get('errors')
    assert len(errors) == 1
    assert errors[0]['error'] == 'ValidationError'
    assert errors[0]['message'] == f"{key} is a required property"


def test_update_service_callback_api_schema_validate_succeeds():
    under_test = {
        "url": "https://some_url.for_service",
        "bearer_token": "something_ten_chars",
        "updated_by_id": str(uuid.uuid4())
    }

    validated = validate(under_test, update_service_callback_api_request_schema)
    assert validated == under_test


def test_update_service_callback_api_schema_validate_fails_with_invalid_keys():
    under_test = {
        "bearers_token": "something_ten_chars",
        "updated_by_id": str(uuid.uuid4())
    }

    with pytest.raises(ValidationError) as e:
        validate(under_test, update_service_callback_api_request_schema)

    errors = json.loads(str(e.value)).get('errors')
    assert len(errors) == 1
    assert errors[0]['error'] == 'ValidationError'
    assert 'bearers_token' in errors[0]['message']
