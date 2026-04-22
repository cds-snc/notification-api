import base64
import io
import json
import pickle

from fido2.utils import websafe_encode
from fido2.webauthn import AttestationObject, AttestedCredentialData, AuthenticatorData
from flask import current_app
from sqlalchemy import and_

from app import db
from app.config import Config
from app.dao.dao_utils import transactional
from app.models import Fido2Key, Fido2Session


def delete_fido2_key(user_id, id):
    db.session.query(Fido2Key).filter(and_(Fido2Key.user_id == user_id, Fido2Key.id == id)).delete()
    db.session.commit()


def get_fido2_key(user_id, id):
    return Fido2Key.query.filter(and_(Fido2Key.user_id == user_id, Fido2Key.id == id)).one()


def list_fido2_keys(user_id):
    return Fido2Key.query.filter(Fido2Key.user_id == user_id).order_by(Fido2Key.created_at.asc()).all()


@transactional
def save_fido2_key(fido2_key):
    return db.session.add(fido2_key)


@transactional
def create_fido2_session(user_id, session):
    delete_fido2_session(user_id)
    db.session.add(Fido2Session(user_id=user_id, session=json.dumps(session)))


def delete_fido2_session(user_id):
    db.session.query(Fido2Session).filter(Fido2Session.user_id == user_id).delete()


def get_fido2_session(user_id):
    session = db.session.query(Fido2Session).filter(Fido2Session.user_id == user_id).one()
    delete_fido2_session(user_id)
    return json.loads(session.session)


def _base64url_decode(value):
    """Decode a base64url-encoded string to bytes.

    Handles missing padding and both base64url and standard base64.
    """
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    # Add padding if needed
    padding = 4 - len(value) % 4
    if padding != 4:
        value += "=" * padding
    # Convert base64url to standard base64
    value = value.replace("-", "+").replace("_", "/")
    return base64.b64decode(value)


def _ensure_bytes(value):
    """Convert various binary-like types to bytes for FIDO2 operations."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError(f"Unsupported binary payload: {type(value)!r}")


class _Fido2CredentialUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        # Handle fido2 library module path changes across versions for backward compatibility.
        # In fido2 0.9.x, AttestedCredentialData was in fido2.ctap2
        # In fido2 1.x, it's in fido2.webauthn (and internally in fido2.ctap2.base)
        # In fido2 2.x, it remains in fido2.webauthn
        _FIDO2_MODULES = ("fido2.ctap2", "fido2.ctap2.base", "fido2.webauthn")
        if name == "AttestedCredentialData" and module in _FIDO2_MODULES:
            return AttestedCredentialData
        if name == "AuthenticatorData" and module in _FIDO2_MODULES:
            return AuthenticatorData
        return super().find_class(module, name)


def deserialize_fido2_key(serialized_key):
    """Deserialize a pickled FIDO2 credential.

    Returns AttestedCredentialData with credential_id attribute.
    Raises ValueError if deserialization fails or credential is malformed.
    """
    raw = base64.b64decode(serialized_key if isinstance(serialized_key, (bytes, bytearray)) else serialized_key.encode("utf-8"))

    # Log the pickle header to understand what version/class was stored
    current_app.logger.info(f"Deserializing FIDO2 key, raw pickle size: {len(raw)} bytes")

    credential = _Fido2CredentialUnpickler(io.BytesIO(raw)).load()

    current_app.logger.info(f"Deserialized credential type: {type(credential).__module__}.{type(credential).__name__}")
    current_app.logger.info(f"Credential attributes: {[a for a in dir(credential) if not a.startswith('_')]}")

    # Verify the deserialized credential has the expected structure
    if not hasattr(credential, "credential_id"):
        current_app.logger.error(
            f"Deserialized credential missing 'credential_id' attribute. Type: {type(credential)}, attrs: {dir(credential)}"
        )
        raise ValueError("Malformed FIDO2 credential: missing credential_id")

    if credential.credential_id is None or len(credential.credential_id) == 0:
        current_app.logger.error("Deserialized credential has empty credential_id")
        raise ValueError("Malformed FIDO2 credential: empty credential_id")

    from fido2.utils import websafe_encode

    cred_id_b64 = websafe_encode(credential.credential_id)
    current_app.logger.info(f"Credential ID (base64url): {cred_id_b64}")
    current_app.logger.info(f"Credential ID length: {len(credential.credential_id)} bytes")

    return credential


def decode_and_register(data, state):
    """Complete FIDO2 registration using the fido2 v2 API.

    Accepts either:
      - A standard WebAuthn RegistrationResponse JSON dict (fido2 v2 format)
      - A legacy dict with top-level 'clientDataJSON' and 'attestationObject' keys
        (these fields are base64url-encoded binary data)
    """
    if "response" in data:
        # Standard WebAuthn RegistrationResponse JSON – pass directly
        response = data
    else:
        # Legacy format: fields are base64url-encoded, need to decode first.
        # Decode from base64url to get the actual binary data
        raw_att = _base64url_decode(data["attestationObject"])
        raw_client_data = _base64url_decode(data["clientDataJSON"])

        # Extract the credential ID from the attestation object so we can
        # populate the required 'rawId' field.
        att_obj = AttestationObject(raw_att)
        cred_id = att_obj.auth_data.credential_data.credential_id

        # Build a RegistrationResponse-compatible dict with base64url-encoded values
        response = {
            "rawId": websafe_encode(cred_id),
            "response": {
                "clientDataJSON": websafe_encode(raw_client_data),
                "attestationObject": websafe_encode(raw_att),
            },
            "type": "public-key",
        }
    auth_data = Config.FIDO2_SERVER.register_complete(state, response)
    return base64.b64encode(pickle.dumps(auth_data.credential_data)).decode("utf8")
