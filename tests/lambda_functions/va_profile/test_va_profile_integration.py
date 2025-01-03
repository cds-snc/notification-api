"""
https://docs.sqlalchemy.org/en/13/core/connections.html

Test the stored function va_profile_opt_in_out by calling it directly, and test the lambda function associated
with VA Profile integration calls this stored function.  The stored function should return True if any row was
created or updated; otherwise, False.
"""

import importlib
import json
from datetime import datetime, timedelta, timezone
from json import dumps, loads
from random import randint
from unittest.mock import Mock, patch

import jwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.x509 import Certificate, load_pem_x509_certificate
from sqlalchemy import delete, func, select, text

from app.models import VAProfileLocalCache
from lambda_functions.va_profile import va_profile_opt_in_out_lambda
from lambda_functions.va_profile.va_profile_opt_in_out_lambda import (
    generate_jwt,
    jwt_is_valid,
    va_profile_opt_in_out_lambda_handler,
)

# Base path for mocks
LAMBDA_MODULE = 'lambda_functions.va_profile.va_profile_opt_in_out_lambda'

# This is a call to a stored procedure.
OPT_IN_OUT = text(
    """\
SELECT va_profile_opt_in_out(:va_profile_id, :communication_item_id, \
:communication_channel_id, :allowed, :source_datetime);"""
)


@pytest.fixture
def mock_env_vars(monkeypatch):
    monkeypatch.setenv('COMP_AND_PEN_OPT_IN_TEMPLATE_ID', 'mock_template_id')
    monkeypatch.setenv('COMP_AND_PEN_SMS_SENDER_ID', 'mock_sms_sender_id')
    monkeypatch.setenv('COMP_AND_PEN_OPT_IN_API_KEY_PARAM_PATH', 'mock_va_notify_api_key_param_path')
    monkeypatch.setenv('COMP_AND_PEN_OPT_IN_API_KEY', 'mock_va_notify_api_key')
    monkeypatch.setenv('COMP_AND_PEN_SERVICE_ID', 'mock_service_id')
    monkeypatch.setenv('ALB_CERTIFICATE_ARN', 'mock_alb_certificate_arn')
    monkeypatch.setenv('ALB_PRIVATE_KEY_PATH', 'mock_alb_private_key_path')
    monkeypatch.setenv('VA_PROFILE_DOMAIN', 'mock_va_profile_domain')


@pytest.fixture
def put_mock(mocker):
    """
    Patch the function that makes a PUT request to VA Profile.  This facilitates inspecting
    the body of the request.
    """

    return mocker.patch(f'{LAMBDA_MODULE}.make_PUT_request')


@pytest.fixture
def post_opt_in_confirmation_mock_return(mocker):
    mock = mocker.patch(f'{LAMBDA_MODULE}.send_comp_and_pen_opt_in_confirmation')
    mock.return_value = None
    return mock


@pytest.fixture(scope='module')
def private_key():
    # This assumes tests are run from the project root directory.
    with open('tests/lambda_functions/va_profile/key.pem', 'rb') as f:
        private_key_bytes = f.read()

    return serialization.load_pem_private_key(private_key_bytes, password=b'test', backend=default_backend())


@pytest.fixture(scope='module')
def public_key() -> Certificate:
    # This assumes tests are run from the project root directory.
    with open('tests/lambda_functions/va_profile/cert.pem', 'rb') as f:
        public_key_bytes = f.read()

    return load_pem_x509_certificate(public_key_bytes).public_key()


@pytest.fixture
def get_integration_testing_public_cert_mock(mocker, public_key):
    """
    Patch the function that loads the public certificate used for integration testing, and make it
    return the same public key used in the other unit tests.
    """

    return mocker.patch(f'{LAMBDA_MODULE}.get_integration_testing_public_cert', return_value=public_key)


@pytest.fixture(scope='module')
def jwt_encoded(private_key):
    """This is a valid JWT encoding."""

    iat = datetime.now(tz=timezone.utc)
    exp = iat + timedelta(minutes=15)
    return jwt.encode({'some': 'payload', 'exp': exp, 'iat': iat}, private_key, algorithm='RS256')


@pytest.fixture
def jwt_encoded_missing_exp(private_key):
    return jwt.encode({'some': 'payload', 'iat': datetime.now(tz=timezone.utc)}, private_key, algorithm='RS256')


@pytest.fixture
def jwt_encoded_missing_iat(private_key):
    return jwt.encode({'some': 'payload', 'exp': datetime.now(tz=timezone.utc)}, private_key, algorithm='RS256')


@pytest.fixture
def jwt_encoded_expired(private_key):
    """This is an invalid JWT encoding because it is expired."""

    iat = datetime.now(tz=timezone.utc) - timedelta(minutes=20)
    exp = iat + timedelta(minutes=15)
    return jwt.encode({'some': 'payload', 'exp': exp, 'iat': iat}, private_key, algorithm='RS256')


@pytest.fixture
def jwt_encoded_reversed(private_key):
    """
    This JWT encoding has an issue time later than the expiration time.  Both times are in the future.
    """

    exp = datetime.now(tz=timezone.utc) + timedelta(days=1)
    iat = exp + timedelta(minutes=15)
    return jwt.encode({'some': 'payload', 'exp': exp, 'iat': iat}, private_key, algorithm='RS256')


@pytest.fixture
def event_dict(jwt_encoded) -> dict:
    """This is a valid event as a Python dictionary."""

    return create_event(
        'txAuditId', 'txAuditId', '2022-03-07T19:37:59.320Z', randint(1000, 100000), 1, 5, True, jwt_encoded
    )


@pytest.fixture
def event_str(event_dict) -> dict:
    """This is a valid event with a JSON string for the body data."""

    event = event_dict.copy()
    event['body'] = dumps(event['body'])
    return event


@pytest.fixture
def event_bytes(event_str) -> dict:
    """This is a valid event with JSON bytes for the body data."""

    event = event_str.copy()
    event['body'] = event['body'].encode()
    return event


def create_event(
    master_tx_audit_id: str,
    tx_audit_id: str,
    source_date: str,
    va_profile_id: int,
    communication_channel_id: int,
    communication_item_id: int,
    is_allowed: bool,
    jwt_value,
) -> dict:
    """
    Return a dictionary in the format of the payload the lambda function expects to
    receive from VA Profile via AWS API Gateway v2.
    """

    return {
        'headers': {
            'Authorization': f'Bearer {jwt_value}',
        },
        'body': {
            'txAuditId': master_tx_audit_id,
            'bios': [
                {
                    'txAuditId': tx_audit_id,
                    'sourceDate': source_date,
                    'vaProfileId': va_profile_id,
                    'communicationChannelId': communication_channel_id,
                    'communicationItemId': communication_item_id,
                    'allowed': is_allowed,
                }
            ],
        },
    }


def test_va_profile_cache_exists(notify_db_session):
    assert notify_db_session.engine.has_table('va_profile_local_cache')


def test_va_profile_stored_function_older_date(notify_db_session, sample_va_profile_local_cache):
    """
    If the given date is older than the existing date, no update should occur.
    """

    va_profile_local_cache = sample_va_profile_local_cache('2022-03-07T19:37:59.320Z', False)

    opt_in_out = OPT_IN_OUT.bindparams(
        va_profile_id=va_profile_local_cache.va_profile_id,
        communication_item_id=va_profile_local_cache.communication_item_id,
        communication_channel_id=va_profile_local_cache.communication_channel_id,
        allowed=True,
        source_datetime='2022-02-07T19:37:59.320Z',  # Older date
    )

    assert not notify_db_session.session.scalar(opt_in_out), 'The date is older than the existing entry.'
    notify_db_session.session.refresh(va_profile_local_cache)
    assert not va_profile_local_cache.allowed, 'The veteran should still be opted-out.'


def test_va_profile_stored_function_newer_date(notify_db_session, sample_va_profile_local_cache):
    """
    If the given date is newer than the existing date, an update should occur.
    """

    va_profile_local_cache = sample_va_profile_local_cache('2022-03-07T19:37:59.320Z', False)
    assert va_profile_local_cache.source_datetime.month == 3

    opt_in_out = OPT_IN_OUT.bindparams(
        va_profile_id=va_profile_local_cache.va_profile_id,
        communication_item_id=va_profile_local_cache.communication_item_id,
        communication_channel_id=va_profile_local_cache.communication_channel_id,
        allowed=True,
        source_datetime='2022-04-07T19:37:59.320Z',  # Newer date
    )

    assert notify_db_session.session.scalar(opt_in_out), 'The date is newer than the existing entry.'
    notify_db_session.session.refresh(va_profile_local_cache)
    assert va_profile_local_cache.source_datetime.month == 4, 'The date should have updated.'


def test_va_profile_stored_function_new_row(notify_db_session):
    """
    Create a new row for a combination of identifiers not already in the database.
    """

    va_profile_id = randint(1000, 100000)

    stmt = (
        select(func.count())
        .select_from(VAProfileLocalCache)
        .where(
            VAProfileLocalCache.va_profile_id == va_profile_id,
            VAProfileLocalCache.communication_item_id == 5,
            VAProfileLocalCache.communication_channel_id == 1,
        )
    )

    assert notify_db_session.session.scalar(stmt) == 0

    opt_in_out = OPT_IN_OUT.bindparams(
        va_profile_id=va_profile_id,
        communication_item_id=5,
        communication_channel_id=1,
        allowed=True,
        source_datetime='2022-02-07T19:37:59.320Z',
    )

    assert notify_db_session.session.scalar(opt_in_out), 'This should create a new row.'

    # Verify one row was created using a delete statement that doubles as teardown.
    stmt = delete(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == va_profile_id,
        VAProfileLocalCache.communication_item_id == 5,
        VAProfileLocalCache.communication_channel_id == 1,
    )
    assert notify_db_session.session.execute(stmt).rowcount == 1
    notify_db_session.session.commit()


def test_jwt_is_valid(jwt_encoded, public_key):
    """
    Test the helper function used to determine if the JWT has a valid signature.
    """

    assert jwt_is_valid(f'Bearer {jwt_encoded}', [public_key])


@pytest.mark.parametrize(
    'invalid_jwt', [jwt_encoded_missing_exp, jwt_encoded_missing_iat, jwt_encoded_expired, jwt_encoded_reversed]
)
def test_jwt_invalid(invalid_jwt, public_key):
    """
    Any JWT that does not meet this criteria should be invalid:
        - Contains exp claim
        - Contains iat claim
        - exp is not expired
        - exp is after iat
    """

    assert not jwt_is_valid(f'Bearer {invalid_jwt}', public_key)


def test_jwt_is_valid_malformed_authorization_header_value(jwt_encoded, public_key):
    """
    Test the helper function used to determine if the JWT has a valid signature.
    """

    assert not jwt_is_valid(f'noBearer {jwt_encoded}', public_key)


def test_va_profile_opt_in_out_lambda_handler_invalid_jwt(put_mock):
    """
    Test the VA Profile integration lambda by sending a request with an invalid jwt encoding.
    """

    # https://www.youtube.com/watch?v=a6iW-8xPw3k
    event = create_event('txAuditId', 'txAuditId', '2022-03-07T19:37:59.320Z', 0, 1, 5, True, '12345')
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 401, '12345 should not be a valid JWT encoding.'
    put_mock.assert_not_called()


def test_va_profile_opt_in_out_lambda_handler_no_authorization_header():
    """
    Test the VA Profile integration lambda by sending a request without an authorization header.
    """

    event = create_event('txAuditId', 'txAuditId', '2022-03-07T19:37:59.320Z', 0, 1, 5, True, '')
    del event['headers']['Authorization']
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 401, 'Requests without an Authorization header should be invalid.'


def test_va_profile_opt_in_out_lambda_handler_missing_attribute(jwt_encoded):
    """
    Test the VA Profile integration lambda by sending a bad request (missing top level attribute).
    """

    event = create_event('txAuditId', 'txAuditId', '2022-03-07T19:37:59.320Z', 0, 1, 5, True, jwt_encoded)
    del event['body']['txAuditId']
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 400
    assert response['body'] == 'A required top level attribute is missing from the request body or has the wrong type.'


@pytest.mark.parametrize(
    'event_body',
    [
        'This is not JSON.',
        '["element1", "element2"]',  # This is valid JSON, but it converts to a list rather than dictionary.
    ],
)
def test_va_profile_opt_in_out_lambda_handler_malformed_json(jwt_encoded, event_body):
    """
    Test the VA Profile integration lambda by sending a request with a body that is not a JSON object.
    """

    event = create_event('txAuditId', 'txAuditId', '2022-03-07T19:37:59.320Z', 1, 1, 5, True, jwt_encoded)
    event['body'] = event_body
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 400, 'The request body must be a JSON object convertible to a Python dictionary.'


def test_va_profile_opt_in_out_lambda_handler_valid_dict(
    notify_db_session,
    event_dict,
    put_mock,
    get_integration_testing_public_cert_mock,
    post_opt_in_confirmation_mock_return,
):
    """
    Test the VA Profile integration lambda by sending a valid request that should create
    a new row in the database.  The AWS lambda function should be able to handle and event
    body that is a Python dictionary.
    """

    # Send a request that should result in a new row.
    response = va_profile_opt_in_out_lambda_handler(event_dict, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 200

    expected_put_body = {
        'dateTime': '2022-03-07T19:37:59.320Z',
        'status': 'COMPLETED_SUCCESS',
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)
    get_integration_testing_public_cert_mock.assert_not_called()

    # Verify one row was created using a delete statement that doubles as teardown.
    stmt = delete(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == event_dict['body']['bios'][0]['vaProfileId'],
        VAProfileLocalCache.communication_item_id == event_dict['body']['bios'][0]['communicationItemId'],
        VAProfileLocalCache.communication_channel_id == event_dict['body']['bios'][0]['communicationChannelId'],
    )
    assert notify_db_session.session.execute(stmt).rowcount == 1
    notify_db_session.session.commit()


def test_va_profile_opt_in_out_lambda_handler_valid_str(
    notify_db_session, event_str, put_mock, post_opt_in_confirmation_mock_return
):
    """
    Test the VA Profile integration lambda by sending a valid request that should create
    a new row in the database.  The AWS lambda function should be able to handle and event
    body that is a JSON string.
    """

    # Send a request that should result in a new row.
    response = va_profile_opt_in_out_lambda_handler(event_str, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 200

    expected_put_body = {
        'dateTime': '2022-03-07T19:37:59.320Z',
        'status': 'COMPLETED_SUCCESS',
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)

    # Verify one row was created using a delete statement that doubles as teardown.
    event = loads(event_str['body'])['bios'][0]
    stmt = delete(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == event['vaProfileId'],
        VAProfileLocalCache.communication_item_id == event['communicationItemId'],
        VAProfileLocalCache.communication_channel_id == event['communicationChannelId'],
    )
    assert notify_db_session.session.execute(stmt).rowcount == 1
    notify_db_session.session.commit()


def test_va_profile_opt_in_out_lambda_handler_valid_bytes(
    notify_db_session, event_bytes, put_mock, post_opt_in_confirmation_mock_return
):
    """
    Test the VA Profile integration lambda by sending a valid request that should create
    a new row in the database.  The AWS lambda function should be able to handle and event
    body that is JSON bytes.
    """

    # Send a request that should result in a new row.
    response = va_profile_opt_in_out_lambda_handler(event_bytes, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 200

    expected_put_body = {
        'dateTime': '2022-03-07T19:37:59.320Z',
        'status': 'COMPLETED_SUCCESS',
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)

    # Verify one row was created using a delete statement that doubles as teardown.
    event = json.loads(event_bytes['body'].decode())['bios'][0]
    stmt = delete(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == event['vaProfileId'],
        VAProfileLocalCache.communication_item_id == event['communicationItemId'],
        VAProfileLocalCache.communication_channel_id == event['communicationChannelId'],
    )
    assert notify_db_session.session.execute(stmt).rowcount == 1
    notify_db_session.session.commit()


def test_va_profile_opt_in_out_lambda_handler_new_row(
    notify_db_session, jwt_encoded, put_mock, post_opt_in_confirmation_mock_return
):
    """
    Test the VA Profile integration lambda by sending a valid request that should create
    a new row in the database.
    """

    va_profile_id = randint(1000, 100000)

    stmt = (
        select(func.count())
        .select_from(VAProfileLocalCache)
        .where(
            VAProfileLocalCache.va_profile_id == va_profile_id,
            VAProfileLocalCache.communication_item_id == 5,
            VAProfileLocalCache.communication_channel_id == 1,
        )
    )

    assert notify_db_session.session.scalar(stmt) == 0

    # Send a request that should result in a new row.
    event = create_event('txAuditId', 'txAuditId', '2022-03-07T19:37:59.320Z', va_profile_id, 1, 5, True, jwt_encoded)
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 200

    expected_put_body = {
        'dateTime': '2022-03-07T19:37:59.320Z',
        'status': 'COMPLETED_SUCCESS',
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)

    # Verify one row was created using a delete statement that doubles as teardown.
    stmt = delete(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == va_profile_id,
        VAProfileLocalCache.communication_item_id == 5,
        VAProfileLocalCache.communication_channel_id == 1,
    )
    assert notify_db_session.session.execute(stmt).rowcount == 1
    notify_db_session.session.commit()


def test_va_profile_opt_in_out_lambda_handler_older_date(
    notify_db_session, jwt_encoded, put_mock, sample_va_profile_local_cache, post_opt_in_confirmation_mock_return
):
    """
    Test the VA Profile integration lambda by sending a valid request with an older date.
    No database update should occur.
    """

    va_profile_local_cache = sample_va_profile_local_cache('2022-03-07T19:37:59.320Z', False)

    event = create_event(
        'txAuditId',
        'txAuditId',
        '2022-02-07T19:37:59.320Z',
        va_profile_local_cache.va_profile_id,
        va_profile_local_cache.communication_channel_id,
        va_profile_local_cache.communication_item_id,
        True,
        jwt_encoded,
    )
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 200

    expected_put_body = {
        'dateTime': '2022-02-07T19:37:59.320Z',
        'status': 'COMPLETED_NOOP',
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)

    notify_db_session.session.refresh(va_profile_local_cache)
    assert not va_profile_local_cache.allowed, 'This should not have been updated.'


@pytest.mark.serial
def test_va_profile_opt_in_out_lambda_handler_newer_date(
    notify_db_session,
    jwt_encoded,
    put_mock,
    sample_va_profile_local_cache,
    post_opt_in_confirmation_mock_return,
):
    """
    Test the VA Profile integration lambda by sending a valid request with a newer date.
    A database update should occur.
    """

    va_profile_local_cache = sample_va_profile_local_cache('2022-03-07T19:37:59.320Z', False)

    event = create_event(
        'txAuditId',
        'txAuditId',
        '2022-04-07T19:37:59.320Z',
        va_profile_local_cache.va_profile_id,
        va_profile_local_cache.communication_channel_id,
        va_profile_local_cache.communication_item_id,
        True,
        jwt_encoded,
    )
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 200

    expected_put_body = {
        'dateTime': '2022-04-07T19:37:59.320Z',
        'status': 'COMPLETED_SUCCESS',
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)

    notify_db_session.session.refresh(va_profile_local_cache)
    assert va_profile_local_cache.allowed, 'This should have been updated.'


@pytest.mark.serial
def test_va_profile_opt_in_out_lambda_handler_KeyError1(jwt_encoded, put_mock, post_opt_in_confirmation_mock_return):
    """
    Test the VA Profile integration lambda by inspecting the PUT request it initiates to
    VA Profile in response to a request.  This test should generate a KeyError in the handler
    that should be caught.
    """

    event = create_event('txAuditId', 'txAuditId', '2022-04-07T19:37:59.320Z', 0, 1, 5, True, jwt_encoded)
    del event['body']['bios'][0]['allowed']
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 400

    expected_put_body = {
        'dateTime': '2022-04-07T19:37:59.320Z',
        'status': 'COMPLETED_FAILURE',
        'messages': [
            {
                'text': "KeyError: The bios dictionary attribute is missing the required attribute 'allowed'.",
                'severity': 'ERROR',
                'potentiallySelfCorrectingOnRetry': False,
            }
        ],
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)


@pytest.mark.serial
def test_va_profile_opt_in_out_lambda_handler_KeyError2(jwt_encoded, put_mock):
    """
    Test the VA Profile integration lambda by inspecting the PUT request is initiates to
    VA Profile in response to a request.  This test should generate a KeyError in the handler
    that should be caught.
    """

    event = create_event('txAuditId', 'txAuditId', '2022-04-07T19:37:59.320Z', 0, 1, 5, True, jwt_encoded)
    del event['body']['bios'][0]['sourceDate']
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 400

    expected_put_body = {
        'dateTime': 'not available',
        'status': 'COMPLETED_FAILURE',
        'messages': [
            {
                'text': "KeyError: The bios dictionary attribute is missing the required attribute 'sourceDate'.",
                'severity': 'ERROR',
                'potentiallySelfCorrectingOnRetry': False,
            }
        ],
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)


@pytest.mark.serial
def test_va_profile_opt_in_out_lambda_handler_wrong_communication_item_id(jwt_encoded, put_mock):
    """
    The lambda should ignore records in which communicationItemId is not 5.
    """

    event = create_event('txAuditId', 'txAuditId', '2022-04-27T16:57:16Z', 2, 1, 4, True, jwt_encoded)
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 200

    expected_put_body = {
        'dateTime': '2022-04-27T16:57:16Z',
        'status': 'COMPLETED_NOOP',
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)


@pytest.mark.serial
def test_va_profile_opt_in_out_lambda_handler_wrong_communication_channel_id(jwt_encoded, put_mock):
    """
    The lambda should ignore records in which communicationChannelId is not 1.
    """

    event = create_event('txAuditId', 'txAuditId', '2022-04-27T16:57:16Z', 2, 2, 5, True, jwt_encoded)
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 200

    expected_put_body = {
        'dateTime': '2022-04-27T16:57:16Z',
        'status': 'COMPLETED_NOOP',
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)


@pytest.mark.serial
def test_va_profile_opt_in_out_lambda_handler_audit_id_mismatch(jwt_encoded, put_mock):
    """
    The request txAuditId should match a bios's txAuditId.
    """

    event = create_event('txAuditId', 'not_txAuditId', '2022-04-27T16:57:16Z', 0, 1, 5, True, jwt_encoded)
    response = va_profile_opt_in_out_lambda_handler(event, None)
    assert isinstance(response, dict)
    assert response['statusCode'] == 200

    expected_put_body = {
        'dateTime': '2022-04-27T16:57:16Z',
        'status': 'COMPLETED_FAILURE',
        'messages': [
            {
                'text': "The record's txAuditId, not_txAuditId, does not match the event's txAuditId, txAuditId.",
                'severity': 'ERROR',
                'potentiallySelfCorrectingOnRetry': False,
            }
        ],
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)


@pytest.mark.serial
@pytest.mark.parametrize(
    'mock_date,expected_month',
    [
        (datetime(2024, 4, 11, 9, 59, tzinfo=timezone.utc), 'April'),  # Before 11th 10:00 AM UTC
        (datetime(2024, 4, 11, 10, 1, tzinfo=timezone.utc), 'May'),  # After 11th 10:00 AM UTC
    ],
)
def test_va_profile_opt_in_out_lambda_handler(
    notify_db_session,
    jwt_encoded,
    mock_env_vars,
    mock_date,
    expected_month,
):
    """
    When the lambda handler is invoked with a path that includes the URL parameter "integration_test",
    verification of the signature on POST request JWTs should use a certificate specifically for integration
    testing.  This public certificate is included with the lambda layer, along with VA Profile's public
    certificates.

    This unit test verifies that the lambda code attempts to load this certificate.
    """

    # Must reload lambda module to properly mock ENV variables defined before running lambda handler
    importlib.reload(va_profile_opt_in_out_lambda)

    # Mock datetime to ensure cutoff logic works as expected
    mock_datetime = patch('lambda_functions.va_profile.va_profile_opt_in_out_lambda.datetime').start()
    mock_datetime.now.return_value = mock_date
    mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

    # Create mock responses for PUT request to VAPROFILE
    mock_put_instance = Mock()
    mock_put_response = Mock()
    mock_put_response.status = 200
    mock_put_response.headers = {'Content-Type': 'application/json'}
    mock_put_response.read.return_value = b'{"dateTime": "2022-04-07T19:37:59.320Z","status": "COMPLETED_SUCCESS",}'
    mock_put_instance.getresponse.return_value = mock_put_response

    # Create mock response for POST request to VANotify
    mock_post_instance = Mock()
    mock_post_response = Mock()
    mock_post_response.status = 201
    mock_post_response.read.return_value = b'{"id":"e7b8cdda-858e-4b6f-a7df-93a71a2edb1e"}'
    mock_post_instance.getresponse.return_value = mock_post_response

    # Use a list of mocks for side_effect to differentiate between calls
    https_connection_side_effect = [mock_put_instance, mock_post_instance]

    # Patch HTTPSConnection with side_effect for PUT request and POST request
    patch(
        'lambda_functions.va_profile.va_profile_opt_in_out_lambda.HTTPSConnection',
        side_effect=https_connection_side_effect,
    ).start()

    mock_ssm = patch('boto3.client').start()
    mock_ssm_instance = mock_ssm.return_value
    mock_ssm_instance.get_parameter.return_value = {'Parameter': {'Value': 'mock_va_notify_api_key'}}

    # Generate a dynamic JWT token using the mocked API key
    # Use to compare against actual request sent
    encoded_header = generate_jwt()

    # Setup new va_profile_id
    va_profile_id = randint(1000, 100000)

    # Check initial state in DB (there should be no records)
    stmt = (
        select(func.count())
        .select_from(VAProfileLocalCache)
        .where(
            VAProfileLocalCache.va_profile_id == va_profile_id,
            VAProfileLocalCache.communication_item_id == 5,
            VAProfileLocalCache.communication_channel_id == 1,
        )
    )
    assert notify_db_session.session.scalar(stmt) == 0

    # Create the event with appropriate parameters for COMP and PEN Opt-In
    event = create_event('txAuditId', 'txAuditId', '2022-04-07T19:37:59.320Z', va_profile_id, 1, 5, True, jwt_encoded)

    # Call the Lambda Handler with the test event
    response = va_profile_opt_in_out_lambda_handler(event, None)

    # Validate the response from the lambda handler
    assert isinstance(response, dict)
    assert response['statusCode'] == 200

    # Assert PUT request to VAProfile was made with correct parameters
    expected_put_body = {
        'dateTime': '2022-04-07T19:37:59.320Z',
        'status': 'COMPLETED_SUCCESS',
    }
    mock_put_instance.request_assert_called_once_with('txAuditId', expected_put_body)
    mock_put_instance.request.assert_called_once()

    # Assert POST request to VANotify was made with correct parameters, including the expected month
    mock_post_instance.request.assert_called_once_with(
        'POST',
        '/v2/notifications/sms',
        body=json.dumps(
            {
                'template_id': 'mock_template_id',
                'recipient_identifier': {'id_type': 'VAPROFILEID', 'id_value': str(va_profile_id)},
                'sms_sender_id': 'mock_sms_sender_id',
                'personalisation': {'month-name': expected_month},
            }
        ),
        headers={'Authorization': f'Bearer {encoded_header}', 'Content-Type': 'application/json'},
    )

    # Verify that one row was created in the DB
    stmt = delete(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == va_profile_id,
        VAProfileLocalCache.communication_item_id == 5,
        VAProfileLocalCache.communication_channel_id == 1,
        VAProfileLocalCache.notification_id == 'e7b8cdda-858e-4b6f-a7df-93a71a2edb1e',
    )
    assert notify_db_session.session.execute(stmt).rowcount == 1
    notify_db_session.session.commit()
