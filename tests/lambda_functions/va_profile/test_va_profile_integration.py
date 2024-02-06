"""
https://docs.sqlalchemy.org/en/13/core/connections.html

Test the stored function va_profile_opt_in_out by calling it directly, and test the lambda function associated
with VA Profile integration calls this stored function.  The stored function should return True if any row was
created or updated; otherwise, False.
"""

import jwt
import pytest
from app.models import VAProfileLocalCache
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.x509 import Certificate, load_pem_x509_certificate
from datetime import datetime, timedelta, timezone
from json import dumps, loads
from lambda_functions.va_profile.va_profile_opt_in_out_lambda import jwt_is_valid, va_profile_opt_in_out_lambda_handler
from random import randint
from sqlalchemy import delete, func, select, text


# Base path for mocks
LAMBDA_MODULE = 'lambda_functions.va_profile.va_profile_opt_in_out_lambda'

# This is a call to a stored procedure.
OPT_IN_OUT = text(
    """\
SELECT va_profile_opt_in_out(:va_profile_id, :communication_item_id, \
:communication_channel_id, :allowed, :source_datetime);"""
)


@pytest.fixture
def put_mock(mocker):
    """
    Patch the function that makes a PUT request to VA Profile.  This facilitates inspecting
    the body of the request.
    """

    return mocker.patch(f'{LAMBDA_MODULE}.make_PUT_request')


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

    stmt = select(func.count()).select_from(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == va_profile_id,
        VAProfileLocalCache.communication_item_id == 5,
        VAProfileLocalCache.communication_channel_id == 1,
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

    assert jwt_is_valid(f'Bearer {jwt_encoded}', public_key)


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


# TODO - The next 3 test functions are highly repetitive.  Is there a way to parametrize them?


def test_va_profile_opt_in_out_lambda_handler_valid_dict(
    notify_db_session,
    event_dict,
    put_mock,
    get_integration_testing_public_cert_mock,
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
    print(event_dict['body']['bios'][0]['vaProfileId'])
    print(event_dict['body']['bios'][0]['communicationItemId'])
    print(event_dict['body']['bios'][0]['communicationChannelId'])
    stmt = delete(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == event_dict['body']['bios'][0]['vaProfileId'],
        VAProfileLocalCache.communication_item_id == event_dict['body']['bios'][0]['communicationItemId'],
        VAProfileLocalCache.communication_channel_id == event_dict['body']['bios'][0]['communicationChannelId'],
    )
    assert notify_db_session.session.execute(stmt).rowcount == 1
    notify_db_session.session.commit()


def test_va_profile_opt_in_out_lambda_handler_valid_str(notify_db_session, event_str, put_mock):
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


def test_va_profile_opt_in_out_lambda_handler_valid_bytes(notify_db_session, event_bytes, put_mock):
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
    event = loads(event_bytes['body'].decode())['bios'][0]
    stmt = delete(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == event['vaProfileId'],
        VAProfileLocalCache.communication_item_id == event['communicationItemId'],
        VAProfileLocalCache.communication_channel_id == event['communicationChannelId'],
    )
    assert notify_db_session.session.execute(stmt).rowcount == 1
    notify_db_session.session.commit()


def test_va_profile_opt_in_out_lambda_handler_new_row(notify_db_session, jwt_encoded, put_mock):
    """
    Test the VA Profile integration lambda by sending a valid request that should create
    a new row in the database.
    """

    va_profile_id = randint(1000, 100000)

    stmt = select(func.count()).select_from(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == va_profile_id,
        VAProfileLocalCache.communication_item_id == 5,
        VAProfileLocalCache.communication_channel_id == 1,
    )

    assert notify_db_session.session.scalar(stmt) == 0

    # Send a request that should result in a new row.
    event = create_event(
        'txAuditId',
        'txAuditId',
        '2022-03-07T19:37:59.320Z',
        va_profile_id,
        1,
        5,
        True,
        jwt_encoded
    )
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
    notify_db_session,
    jwt_encoded,
    put_mock,
    sample_va_profile_local_cache,
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
        jwt_encoded
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
        jwt_encoded
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
def test_va_profile_opt_in_out_lambda_handler_KeyError1(jwt_encoded, put_mock):
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
def test_va_profile_opt_in_out_lambda_handler_integration_testing(
    notify_db_session,
    jwt_encoded,
    put_mock,
    get_integration_testing_public_cert_mock,
):
    """
    When the lambda handler is invoked with a path that includes the URL parameter "integration_test",
    verification of the signature on POST request JWTs should use a certificate specifically for integration
    testing.  This public certificate is included with the lambda layer, along with VA Profile's public
    certificates.

    This unit test verifies that the lambda code attempts to load this certificate.
    """

    va_profile_id = randint(1000, 100000)

    stmt = select(func.count()).select_from(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == va_profile_id,
        VAProfileLocalCache.communication_item_id == 5,
        VAProfileLocalCache.communication_channel_id == 1,
    )

    assert notify_db_session.session.scalar(stmt) == 0

    event = create_event('txAuditId', 'txAuditId', '2022-04-07T19:37:59.320Z', va_profile_id, 1, 5, True, jwt_encoded)
    event['queryStringParameters'] = {'integration_test': "the value doesn't matter"}
    response = va_profile_opt_in_out_lambda_handler(event, None)

    assert isinstance(response, dict)
    assert response['statusCode'] == 200
    assert response.get('headers', {}).get('Content-Type', '') == 'application/json'
    response_body = loads(response.get('body', '{}'))
    assert 'put_body' in response_body

    expected_put_body = {
        'dateTime': '2022-04-07T19:37:59.320Z',
        'status': 'COMPLETED_SUCCESS',
    }

    put_mock.assert_called_once_with('txAuditId', expected_put_body)
    get_integration_testing_public_cert_mock.assert_called_once()
    assert response_body['put_body'] == expected_put_body

    # Verify one row was created using a delete statement that doubles as teardown.
    stmt = delete(VAProfileLocalCache).where(
        VAProfileLocalCache.va_profile_id == va_profile_id,
        VAProfileLocalCache.communication_item_id == 5,
        VAProfileLocalCache.communication_channel_id == 1,
    )
    assert notify_db_session.session.execute(stmt).rowcount == 1
    notify_db_session.session.commit()


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
