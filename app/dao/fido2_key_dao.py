import base64
import io
import json
import pickle

from fido2.utils import websafe_encode
from fido2.webauthn import AttestationObject, AttestedCredentialData, AuthenticatorData
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
    raw = base64.b64decode(serialized_key if isinstance(serialized_key, (bytes, bytearray)) else serialized_key.encode("utf-8"))
    return _Fido2CredentialUnpickler(io.BytesIO(raw)).load()


def decode_and_register(data, state):
    """Complete FIDO2 registration using the fido2 v2 API.

    Accepts either:
      - A standard WebAuthn RegistrationResponse JSON dict (fido2 v2 format)
      - A legacy dict with top-level 'clientDataJSON' and 'attestationObject' keys
    """
    if "response" in data:
        # Standard WebAuthn RegistrationResponse JSON – pass directly
        response = data
    else:
        # Legacy format: build a RegistrationResponse-compatible dict.
        # Extract the credential ID from the attestation object so we can
        # populate the required 'rawId' field.
        raw_att = _ensure_bytes(data["attestationObject"])
        att_obj = AttestationObject(raw_att)
        cred_id = att_obj.auth_data.credential_data.credential_id
        response = {
            "rawId": websafe_encode(cred_id),
            "response": {
                "clientDataJSON": websafe_encode(_ensure_bytes(data["clientDataJSON"])),
                "attestationObject": websafe_encode(raw_att),
            },
            "type": "public-key",
        }
    auth_data = Config.FIDO2_SERVER.register_complete(state, response)
    return base64.b64encode(pickle.dumps(auth_data.credential_data)).decode("utf8")
