import secrets
from datetime import datetime
from typing import Callable, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm.exc import NoResultFound

from app import db
from app.dao.dao_utils import transactional, version_class
from app.models import ApiKey


@transactional
@version_class(ApiKey)
def save_model_api_key(api_key: ApiKey, secret_generator: Optional[Callable[[], str]] = None) -> None:
    """Adds or updates the API key in the database with the provided information.

    Args:
        api_key (ApiKey): The API key object containing the information to add or update in the database.
        secret_generator (Optional[Callable[[], str]]): Optional function to generate the API key secret.
                                                        If not provided, uses the default token generator.
    """
    if not api_key.id:
        api_key.id = uuid4()  # must be set now so version history model can use same id

    if not api_key.secret:
        if secret_generator:
            api_key.secret = secret_generator()
        else:
            api_key.secret = secrets.token_urlsafe(64)

    db.session.add(api_key)


@transactional
@version_class(ApiKey)
def expire_api_key(
    service_id: UUID,
    api_key_id: UUID,
) -> None:
    """Revokes API key for the given service with the given key id.

    Args:
        service_id (UUID): The id of the service
        api_key_id (UUID): The id of the key to revoke
    """
    stmt = select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.service_id == service_id)

    api_key: ApiKey = db.session.scalars(stmt).one()
    api_key.expiry_date = datetime.utcnow()
    api_key.revoked = True

    db.session.add(api_key)


def get_model_api_key(
    key_id: UUID,
) -> ApiKey:
    """Retrieves the API key with the given id.

    Args:
        key_id (UUID): The API key uuid to lookup.

    Returns:
        ApiKey: The API key with the given id if one is found.

    Raises:
        NoResultFound: If there is no key with the given ID.
    """
    stmt = select(ApiKey).where(ApiKey.id == key_id)
    return db.session.scalars(stmt).one()


def get_model_api_keys(service_id: UUID, include_revoked: bool = False) -> list[ApiKey]:
    """Retrieves the API keys associated with the given service id. By default, only active keys are returned.

    Args:
        service_id (UUID): The service id uuid to use when looking up API keys.
        include_revoked (bool): If True, include revoked keys in the results. Defaults to False.

    Returns:
        list[ApiKey]: The API keys associated with the given service id, if any are found.

    Raises:
        NoResultFound: If there is no key associated with the given service, or the key has been revoked.
    """
    stmt = select(ApiKey).where(ApiKey.service_id == service_id)
    if not include_revoked:
        stmt = stmt.where(ApiKey.revoked.is_(False))

    keys = db.session.scalars(stmt).all()

    if not keys:
        raise NoResultFound()

    return keys


def get_unsigned_secrets(service_id: UUID) -> list[str]:
    """
    This method can only be exposed to the Authentication of the api calls.

    Args:
        service_id (UUID): The ID of the service to pull the secrets from

    Returns:
        list[str]: The list of secrets retrieved
    """
    stmt = select(ApiKey).where(ApiKey.service_id == service_id, ApiKey.revoked.is_(False))
    api_keys = db.session.scalars(stmt).all()
    keys = [x.secret for x in api_keys]
    return keys


def get_unsigned_secret(key_id: UUID) -> str:
    """Retrieve the secret for a given key.

    Args:
        key_id (UUID): The id related to the secret being looked up

    Returns:
        str: The secret
    """
    stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.revoked.is_(False))
    api_key = db.session.scalars(stmt).one()
    return api_key.secret
