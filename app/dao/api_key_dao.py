import uuid
from datetime import datetime, timedelta

from flask import current_app
from itsdangerous import BadSignature
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from app import db, signer_api_key
from app.dao.dao_utils import transactional, version_class
from app.models import ApiKey


@transactional
def resign_api_keys(unsafe: bool = False):
    """Resign the _secret column of the api_keys table with (potentially) a new key.

    Args:
        unsafe (bool, optional): resign regardless of whether the unsign step fails with a BadSignature.
        Defaults to False.

    Raises:
        e: BadSignature if the unsign step fails and unsafe is False.
    """
    rows = ApiKey.query.all()  # noqa
    current_app.logger.info(f"Resigning {len(rows)} api keys")

    for row in rows:
        try:
            unsigned_secret = getattr(row, "secret")  # unsign the secret
        except BadSignature as e:
            if unsafe:
                unsigned_secret = signer_api_key.verify_unsafe(row._secret)
            else:
                current_app.logger.error(f"BadSignature for api_key {row.id}, using verify_unsafe instead")
                raise e
        setattr(row, "secret", unsigned_secret)  # resigns the api key secret with (potentially) a new signing secret
    db.session.bulk_save_objects(rows)


@transactional
@version_class(ApiKey)
def save_model_api_key(api_key):
    if not api_key.id:
        api_key.id = uuid.uuid4()  # must be set now so version history model can use same id
    api_key.secret = uuid.uuid4()
    db.session.add(api_key)


@transactional
@version_class(ApiKey)
def expire_api_key(service_id, api_key_id):
    api_key = ApiKey.query.filter_by(id=api_key_id, service_id=service_id).one()
    api_key.expiry_date = datetime.utcnow()
    db.session.add(api_key)


# TODO: get rid of the sign_dangerously section once we've removed DANGEROUS_SALT and resigned the api keys
def get_api_key_by_secret(secret):
    signed_with_all_keys = signer_api_key.sign_with_all_keys(str(secret))
    for signed_secret in signed_with_all_keys:
        try:
            return db.on_reader().query(ApiKey).filter_by(_secret=signed_secret).options(joinedload("service")).one()
        except NoResultFound:
            pass

    signed_dangerous_with_all_keys = signer_api_key.sign_with_all_dangerously_salted_keys(str(secret))
    for signed_secret in signed_dangerous_with_all_keys:
        try:
            return db.on_reader().query(ApiKey).filter_by(_secret=signed_secret).options(joinedload("service")).one()
        except NoResultFound:
            pass
    raise NoResultFound()


def get_model_api_keys(service_id, id=None):
    if id:
        return ApiKey.query.filter_by(id=id, service_id=service_id, expiry_date=None).one()
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    return ApiKey.query.filter(
        or_(ApiKey.expiry_date == None, func.date(ApiKey.expiry_date) > seven_days_ago),  # noqa
        ApiKey.service_id == service_id,
    ).all()


def get_unsigned_secrets(service_id):
    """
    This method can only be exposed to the Authentication of the api calls.
    """
    api_keys = ApiKey.query.filter_by(service_id=service_id, expiry_date=None).all()
    keys = [x.secret for x in api_keys]
    return keys


def get_unsigned_secret(key_id):
    """
    This method can only be exposed to the Authentication of the api calls.
    """
    api_key = ApiKey.query.filter_by(id=key_id, expiry_date=None).one()
    return api_key.secret
