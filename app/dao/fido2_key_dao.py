import base64
import json
import pickle  # nosec

from fido2.webauthn import AttestationObject, CollectedClientData
from sqlalchemy import asc, delete, select

from app import db
from app.config import Config
from app.dao.dao_utils import transactional
from app.models import Fido2Key, Fido2Session


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


def list_fido2_keys(user_id):
    stmt = select(Fido2Key).where(Fido2Key.user_id == user_id).order_by(asc(Fido2Key.created_at))
    return db.session.scalars(stmt).all()


@transactional
def save_fido2_key(fido2_key):
    return db.session.add(fido2_key)


@transactional
def create_fido2_session(
    user_id,
    session,
):
    delete_fido2_session(user_id)
    db.session.add(Fido2Session(user_id=user_id, session=json.dumps(session)))


def delete_fido2_session(user_id):
    stmt = delete(Fido2Session).where(Fido2Session.user_id == user_id)
    db.session.execute(stmt)
    db.session.commit()


def get_fido2_session(user_id):
    stmt = select(Fido2Session).where(Fido2Session.user_id == user_id)
    session = db.session.scalars(stmt).one()
    delete_fido2_session(user_id)
    return json.loads(session.session)


def decode_and_register(
    data,
    state,
):
    client_data = CollectedClientData(data['clientDataJSON'])
    att_obj = AttestationObject(data['attestationObject'])

    auth_data = Config.FIDO2_SERVER.register_complete(state, client_data, att_obj)

    return base64.b64encode(pickle.dumps(auth_data.credential_data)).decode('utf8')
