import json
import logging
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from flask import Flask, g
from notifications_python_client.authentication import create_jwt_token
from notifications_utils import logging as notify_logging
from notifications_utils import request_helper

from app.authentication import auth
from app.authentication.audit import audit_jwt_event


@pytest.fixture
def audit_app(caplog):
    app = Flask("jwt-audit-tests")
    request_helper.init_app(app)
    caplog.set_level(logging.INFO, logger=app.name)
    return app


@pytest.fixture
def audit_service(mocker):
    service_id = uuid4()
    keys = [
        SimpleNamespace(id=uuid4(), service_id=service_id, secret=secret, expiry_date=None) for secret in ("a" * 32, "b" * 32)
    ]
    service = SimpleNamespace(id=service_id, active=True, api_keys=keys)
    mocker.patch("app.authentication.auth.dao_fetch_service_by_id_with_api_keys", return_value=service)
    return service


def audit_records(caplog):
    return [record for record in caplog.records if hasattr(record, "event")]


@pytest.mark.parametrize("key_index", [0, 1])
def test_success_emits_only_validated_event(audit_app, audit_service, caplog, key_index):
    key = audit_service.api_keys[key_index]
    token = create_jwt_token(key.secret, str(audit_service.id))
    with audit_app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        auth.requires_auth()
        assert g.api_user is key

    records = audit_records(caplog)
    assert [record.event for record in records] == ["jwt.validated"]
    assert records[0].api_key_id == key.id
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


@pytest.mark.parametrize("algorithm, reason", [("HS256", "invalid_signature"), ("HS512", "unsupported_algorithm")])
def test_all_keys_fail_emits_one_validation_failure(audit_app, audit_service, caplog, algorithm, reason):
    token = jwt.encode({"iss": str(audit_service.id), "iat": int(datetime.now().timestamp())}, "c" * 64, algorithm=algorithm)
    with audit_app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        with pytest.raises(auth.AuthError) as exc:
            auth.requires_auth()
    assert exc.value.code == 403
    records = audit_records(caplog)
    assert [(record.event, record.reason) for record in records] == [("jwt.validation_failed", reason)]
    assert records[0].api_key_id is None


def test_revoked_key_emits_authorization_failure(audit_app, audit_service, caplog):
    key = audit_service.api_keys[1]
    key.expiry_date = datetime.now()
    token = create_jwt_token(key.secret, str(audit_service.id))
    with audit_app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        with pytest.raises(auth.AuthError, match="API key revoked") as exc:
            auth.requires_auth()
        assert "api_user" not in g
    assert exc.value.code == 403
    records = audit_records(caplog)
    assert [(record.event, record.reason) for record in records] == [("jwt.authorization_failed", "api_key_revoked")]
    assert records[0].service_id == audit_service.id
    assert records[0].api_key_id == key.id


@pytest.mark.parametrize(
    "auth_fn, config_key",
    [
        (auth.requires_admin_auth, "ADMIN_CLIENT_USER_NAME"),
        (auth.requires_sre_auth, "SRE_USER_NAME"),
        (auth.requires_cache_clear_auth, "CACHE_CLEAR_USER_NAME"),
        (auth.requires_cypress_auth, "CYPRESS_AUTH_USER_NAME"),
    ],
)
def test_privileged_wrong_issuer_is_audited(audit_app, caplog, auth_fn, config_key):
    audit_app.config[config_key] = "expected-issuer"
    token = create_jwt_token("a" * 32, "wrong-issuer")
    with audit_app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        with pytest.raises(auth.AuthError) as exc:
            auth_fn()
    assert exc.value.code == 401
    records = audit_records(caplog)
    assert [(record.event, record.reason) for record in records] == [("jwt.authorization_failed", "invalid_issuer")]
    assert records[0].token_issuer == "wrong-issuer"


def test_production_formatter_preserves_structured_fields_and_request_id(audit_app, caplog):
    service_id, key_id = uuid4(), uuid4()
    secret = "a" * 32
    token = create_jwt_token(secret, str(service_id))
    audit_app.config["NOTIFY_TRACE_ID_HEADER"] = "X-Audit-Trace"
    with audit_app.test_request_context(
        "/notifications", headers={"X-Audit-Trace": "canonical-trace-id", "X-Request-ID": "different-id"}
    ):
        audit_app.preprocess_request()
        audit_jwt_event("jwt.validated", token, service_id=service_id, api_key_id=key_id)
        record = audit_records(caplog)[0]
        assert record.request_id == "canonical-trace-id"
        notify_logging.AppNameFilter("test").filter(record)
        notify_logging.RequestIdFilter().filter(record)
        formatter = notify_logging.JSONFormatter(notify_logging.LOG_FORMAT, notify_logging.TIME_FORMAT)
        output = formatter.format(record)

    fields = json.loads(output)
    assert fields["event"] == "jwt.validated"
    assert fields["service_id"] == str(service_id)
    assert fields["api_key_id"] == str(key_id)
    assert fields["requestId"] == "canonical-trace-id"
    assert fields["path"] == "/notifications"
    assert fields["algorithm"] == "HS256"
    assert token not in output
    assert secret not in output


def test_malformed_token_is_still_audited(audit_app, caplog):
    with audit_app.test_request_context(headers={"Authorization": "Bearer malformed"}):
        with pytest.raises(auth.AuthError) as exc:
            auth.requires_auth()
    assert exc.value.code == 403
    records = audit_records(caplog)
    assert [(record.event, record.reason) for record in records] == [("jwt.validation_failed", "invalid_token")]
    assert records[0].token_metadata == "unavailable"
