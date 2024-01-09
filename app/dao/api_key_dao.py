import uuid
from datetime import datetime, timedelta

from app import db
from app.models import ApiKey

from app.dao.dao_utils import transactional, version_class

from sqlalchemy import or_, func, select


@transactional
@version_class(ApiKey)
def save_model_api_key(api_key):
    if not api_key.id:
        api_key.id = uuid.uuid4()  # must be set now so version history model can use same id
    if not api_key.secret:
        api_key.secret = uuid.uuid4()
    db.session.add(api_key)


@transactional
@version_class(ApiKey)
def expire_api_key(
    service_id,
    api_key_id,
):
    stmt = select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.service_id == service_id)
    api_key = db.session.scalars(stmt).one()
    api_key.expiry_date = datetime.utcnow()
    db.session.add(api_key)


def get_model_api_keys(
    service_id,
    id=None,
):
    if id:
        stmt = select(ApiKey).where(ApiKey.id == id, ApiKey.service_id == service_id, ApiKey.expiry_date.is_(None))
        return db.session.scalars(stmt).one()

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    stmt = select(ApiKey).where(
        or_(ApiKey.expiry_date.is_(None), func.date(ApiKey.expiry_date) > seven_days_ago),
        ApiKey.service_id == service_id,
    )

    return db.session.scalars(stmt).all()


def get_unsigned_secrets(service_id):
    """
    This method can only be exposed to the Authentication of the api calls.
    """
    stmt = select(ApiKey).where(ApiKey.service_id == service_id, ApiKey.expiry_date.is_(None))
    api_keys = db.session.scalars(stmt).all()
    keys = [x.secret for x in api_keys]
    return keys


def get_unsigned_secret(key_id):
    """
    This method can only be exposed to the Authentication of the api calls.
    """
    stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.expiry_date.is_(None))
    api_key = db.session.scalars(stmt).one()
    return api_key.secret
