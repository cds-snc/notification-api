from app import db
from app.models import Fido2Key

from app.dao.dao_utils import (
    transactional
)

from sqlalchemy import and_


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
