import base64
import pickle  # nosec

from fido2.webauthn import AttestationObject, CollectedClientData
from sqlalchemy import delete, select

from app import db
from app.config import Config
from app.models import Fido2Key


def delete_fido2_key(
    user_id,
    fido_key_id,
):
    stmt = delete(Fido2Key).where(Fido2Key.user_id == user_id, Fido2Key.id == fido_key_id)
    db.session.execute(stmt)
    db.session.commit()


def get_fido2_key(
    user_id,
    fido_key_id,
):
    stmt = select(Fido2Key).where(Fido2Key.user_id == user_id, Fido2Key.id == fido_key_id)
    return db.session.scalars(stmt).one()


def decode_and_register(
    data,
    state,
):
    client_data = CollectedClientData(data['clientDataJSON'])
    att_obj = AttestationObject(data['attestationObject'])

    auth_data = Config.FIDO2_SERVER.register_complete(state, client_data, att_obj)

    return base64.b64encode(pickle.dumps(auth_data.credential_data)).decode('utf8')
