import pytest
from jsonschema.exceptions import ValidationError

from app.v2.inbound_sms.inbound_sms_schemas import (
    get_inbound_sms_request,
    get_inbound_sms_response,
    get_inbound_sms_single_response,
)
from app.schema_validation import validate


valid_inbound_sms = {
    'user_number': '447700900111',
    'created_at': '2017-11-02T15:07:57.197546Z',
    'service_id': 'a5149c32-f03b-4711-af49-ad6993797d45',
    'id': '342786aa-23ce-4695-9aad-7f79e68ee29a',
    'notify_number': 'testing',
    'content': 'Hello',
}

valid_inbound_sms_list = {'received_text_messages': [valid_inbound_sms], 'links': {'current': valid_inbound_sms['id']}}

invalid_inbound_sms = {
    'user_number': '447700900111',
    'created_at': '2017-11-02T15:07:57.197546',
    'service_id': 'a5149c32-f03b-4711-af49-ad6993797d45',
    'id': '342786aa-23ce-4695-9aad-7f79e68ee29a',
    'notify_number': 'testing',
}

invalid_inbound_sms_list = {'received_text_messages': [invalid_inbound_sms]}


@pytest.mark.parametrize('request_args', [{'older_than': '6ce466d0-fd6a-11e5-82f5-e0accb9d11a6'}, {}])
def test_valid_inbound_sms_request_json(client, request_args):
    validate(request_args, get_inbound_sms_request)


def test_invalid_inbound_sms_request_json(client):
    with pytest.raises(expected_exception=ValidationError):
        validate({'user_number': '447700900111'}, get_inbound_sms_request)


def test_valid_inbound_sms_response_json(client):
    assert validate(valid_inbound_sms, get_inbound_sms_single_response) == valid_inbound_sms


def test_valid_inbound_sms_list_response_json(client):
    validate(valid_inbound_sms_list, get_inbound_sms_response)


def test_invalid_inbound_sms_response_json(client):
    with pytest.raises(expected_exception=ValidationError):
        validate(invalid_inbound_sms, get_inbound_sms_single_response)


def test_invalid_inbound_sms_list_response_json(client):
    with pytest.raises(expected_exception=ValidationError):
        validate(invalid_inbound_sms_list, get_inbound_sms_response)
