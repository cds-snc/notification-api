import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from app import db, signer_api_key
from app.dao.dao_utils import transactional, version_class
from app.models import ApiKey


@transactional
def resign_api_keys():
    api_keys = ApiKey.query.all()  # noqa
    for api_key in api_keys:
        api_key.secret = api_key.secret  # verifies with the getter and resigns with the setter
    db.session.bulk_save_objects(api_keys)


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


# TODO: get rid of the exception handling once we've removed DANGEROUS_SALT and resigned the api keys
def get_api_key_by_secret(secret):
    try:
        return (
            db.on_reader().query(ApiKey).filter_by(_secret=signer_api_key.sign(str(secret))).options(joinedload("service")).one()
        )
    except NoResultFound:
        return (
            db.on_reader()
            .query(ApiKey)
            .filter_by(_secret=signer_api_key.sign_dangerous(str(secret)))
            .options(joinedload("service"))
            .one()
        )


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
