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
from app.utils import rate_limit_db_calls


@transactional
def resign_api_keys(resign: bool, unsafe: bool = False):
    """Resign the _secret column of the api_keys table with (potentially) a new key.

    Args:
        resign (bool): whether to resign the api keys
        unsafe (bool, optional): resign regardless of whether the unsign step fails with a BadSignature.
        Defaults to False.

    Raises:
        e: BadSignature if the unsign step fails and unsafe is False.
    """
    rows = ApiKey.query.all()  # noqa
    current_app.logger.info(f"Total of {len(rows)} api keys")
    rows_to_update = []

    for row in rows:
        try:
            old_signature = row._secret
            unsigned_secret = getattr(row, "secret")  # unsign the secret
        except BadSignature as e:
            if unsafe:
                unsigned_secret = signer_api_key.verify_unsafe(row._secret)
            else:
                current_app.logger.error(f"BadSignature for api_key {row.id}, using verify_unsafe instead")
                raise e
        setattr(row, "secret", unsigned_secret)  # resigns the api key secret with (potentially) a new signing secret
        if old_signature != row._secret:
            rows_to_update.append(row)
        if not resign:
            row._secret = old_signature  # reset the signature to the old value

    if resign:
        current_app.logger.info(f"Resigning {len(rows_to_update)} api keys")
        db.session.bulk_save_objects(rows)
    elif not resign:
        current_app.logger.info(f"{len(rows_to_update)} api keys need resigning")


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


@transactional
@rate_limit_db_calls(key_prefix="update_api_key_last_used", period_seconds=60)
def update_last_used_api_key(api_key_id, last_used=None) -> None:
    """
    Update the last_used_timestamp of an API key using a direct SQLAlchemy update.
    Using update() directly is more efficient than loading the model instance.
    Setting `synchronize_session=False` improves performance and can be used since we
    don't need to access the updated value in the same session.
    Rate limited to once per minute using Redis.
    """
    timestamp = last_used if last_used else datetime.utcnow()

    ApiKey.query.filter_by(id=api_key_id).update({"last_used_timestamp": timestamp}, synchronize_session=False)


@transactional
@version_class(ApiKey)
def update_compromised_api_key_info(service_id, api_key_id, compromised_info):
    api_key = ApiKey.query.filter_by(id=api_key_id, service_id=service_id).one()
    api_key.compromised_key_info = compromised_info
    db.session.add(api_key)


def get_api_key_by_secret(secret, service_id=None):
    # Check the first part of the secret is the gc prefix
    if current_app.config["API_KEY_PREFIX"] != secret[: len(current_app.config["API_KEY_PREFIX"])]:
        raise ValueError()

    # Check if the remaining part of the secret is a the valid api key
    token = secret[-36:]
    signed_with_all_keys = signer_api_key.sign_with_all_keys(str(token))
    for signed_secret in signed_with_all_keys:
        try:
            api_key = db.on_reader().query(ApiKey).filter_by(_secret=signed_secret).options(joinedload("service")).one()
        except NoResultFound:
            raise NoResultFound()

    # Check the middle portion of the secret is the valid service id
    if api_key and api_key.service_id:
        if len(secret) >= 79:
            service_id_from_token = str(secret[-73:-37])
            if str(api_key.service_id) != service_id_from_token:
                raise ValueError()
        else:
            raise ValueError()
    if api_key:
        return api_key
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
