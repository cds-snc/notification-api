from datetime import datetime, timezone

import jwt
from flask import current_app, request


def audit_jwt_event(event, token=None, service_id=None, api_key_id=None, **fields):
    """Write a safe, structured JWT audit event to the application log."""
    metadata = _token_metadata(token)
    metadata.update(
        {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": request.method,
            "path": request.path,
            "endpoint": request.endpoint,
            "user_agent": request.headers.get("User-Agent"),
            "source_ip": request.remote_addr,
            "request_id": getattr(request, "request_id", None),
            "traceparent": request.headers.get("traceparent"),
            "service_id": service_id,
            "api_key_id": api_key_id,
            **fields,
        }
    )
    current_app.logger.info("JWT audit event", extra=metadata)


def _token_metadata(token):
    if not token:
        return {}

    metadata = {}
    try:
        metadata["algorithm"] = jwt.get_unverified_header(token).get("alg")
        claims = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
        if "iss" in claims:
            # iss is only a candidate identity until signature validation succeeds.
            metadata["token_issuer"] = claims["iss"]
        for claim in ("sub", "jti", "iat", "exp"):
            if claim in claims:
                metadata[claim] = claims[claim]
    except jwt.PyJWTError:
        metadata["token_metadata"] = "unavailable"
    return metadata
