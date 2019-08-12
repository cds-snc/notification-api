from app import db
from app.models import Fido2Key, Fido2Session
from app.config import Config

from app.dao.dao_utils import (
    transactional
)

from sqlalchemy import and_

from fido2.client import ClientData
from fido2.ctap2 import AttestationObject
import json
import pickle
import base64


def delete_fido2_key(user_id, id):
    db.session.query(Fido2Key).filter(
        and_(Fido2Key.user_id == user_id, Fido2Key.id == id)
    ).delete()
    db.session.commit()


def get_fido2_key(user_id, id):
    return Fido2Key.query.filter(
        and_(Fido2Key.user_id == user_id, Fido2Key.id == id)
    ).one()


def list_fido2_keys(user_id):
    return Fido2Key.query.filter(
        Fido2Key.user_id == user_id
    ).order_by(Fido2Key.created_at.asc()).all()


@transactional
def save_fido2_key(fido2_key):
    return db.session.add(fido2_key)


@transactional
def create_fido2_session(user_id, session):
    delete_fido2_session(user_id)
    db.session.add(
        Fido2Session(user_id=user_id, session=json.dumps(session))
    )


def delete_fido2_session(user_id):
    db.session.query(Fido2Session).filter(
        Fido2Session.user_id == user_id
    ).delete()


def get_fido2_session(user_id):
    session = db.session.query(Fido2Session).filter(
        Fido2Session.user_id == user_id
    ).one()
    delete_fido2_session(user_id)
    return json.loads(session.session)


def decode_and_register(data, state):
    client_data = ClientData(data['clientDataJSON'])
    att_obj = AttestationObject(data['attestationObject'])

    auth_data = Config.FIDO2_SERVER.register_complete(
        state,
        client_data,
        att_obj
    )

    return base64.b64encode(pickle.dumps(auth_data.credential_data)).decode('utf8')
