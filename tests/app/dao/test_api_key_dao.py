from datetime import datetime, timedelta
import uuid
from unittest.mock import Mock

import pytest
from freezegun import freeze_time
from sqlalchemy import delete, func, select
from sqlalchemy.orm.exc import NoResultFound

from app.constants import KEY_TYPE_NORMAL, SECRET_TYPE_DEFAULT
from app.dao.api_key_dao import (
    get_model_api_key,
    save_model_api_key,
    get_model_api_keys,
    get_unsigned_secrets,
    get_unsigned_secret,
    expire_api_key,
    update_api_key_expiry,
)
from app.models import ApiKey, Service


def test_save_api_key_should_create_new_api_key_and_history(notify_db_session, sample_service):
    service = sample_service()
    api_key = ApiKey(
        **{'service': service, 'name': service.name, 'created_by': service.created_by, 'key_type': KEY_TYPE_NORMAL}
    )
    save_model_api_key(api_key)

    ApiKeyHistory = ApiKey.get_history_model()

    try:
        assert api_key.version == 1

        stmt = select(ApiKeyHistory).where(ApiKeyHistory.id == api_key.id)
        history = notify_db_session.session.scalars(stmt).one()

        assert history.version == api_key.version
    finally:
        # Teardown
        # Clear API Key history
        stmt = delete(ApiKeyHistory).where(ApiKeyHistory.id == api_key.id)
        notify_db_session.session.execute(stmt)

        # Clear API Key
        stmt = delete(ApiKey).where(ApiKey.id == api_key.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_expire_api_key_should_update_the_api_key_and_create_history_record(
    notify_db_session,
    sample_api_key,
):
    api_key = sample_api_key()
    assert api_key.expiry_date > datetime.utcnow()
    assert not api_key.revoked

    ApiKeyHistory = ApiKey.get_history_model()
    stmt = select(func.count()).select_from(ApiKeyHistory).where(ApiKeyHistory.id == api_key.id)
    assert notify_db_session.session.scalar(stmt) == 1

    expire_api_key(service_id=api_key.service_id, api_key_id=api_key.id)

    notify_db_session.session.refresh(api_key)
    assert api_key.expiry_date <= datetime.utcnow(), 'The API key should be expired.'
    assert api_key.revoked, 'The API key should have revoked=True when expired.'
    assert notify_db_session.session.scalar(stmt) == 2, 'Should have created a new history row'


def test_get_api_key_should_raise_exception_when_api_key_does_not_exist(sample_service, fake_uuid):
    with pytest.raises(NoResultFound):
        get_model_api_key(fake_uuid)


def test_get_api_keys_should_raise_exception_when_api_key_does_not_exist(sample_service, fake_uuid):
    with pytest.raises(NoResultFound):
        print(get_model_api_keys(sample_service().id))


def test_should_return_api_keys_for_service(sample_api_key):
    api_key1 = sample_api_key()
    api_key2 = get_model_api_keys(service_id=api_key1.service_id)
    assert len(api_key2) == 1
    assert api_key2[0] == api_key1


def test_should_return_api_key_for_id(sample_api_key):
    api_key1 = sample_api_key()
    api_key2 = get_model_api_key(key_id=api_key1.id)
    assert api_key2 == api_key1


def test_should_return_api_key_for_id_when_revoked(sample_api_key):
    api_key1 = sample_api_key(expired=True)
    api_key2 = get_model_api_key(key_id=api_key1.id)
    assert api_key2 == api_key1


def test_should_return_unsigned_api_keys_for_service_id(sample_api_key):
    api_key = sample_api_key()
    unsigned_api_key = get_unsigned_secrets(api_key.service_id)
    assert len(unsigned_api_key) == 1
    assert api_key._secret != unsigned_api_key[0]
    assert unsigned_api_key[0] == api_key.secret


def test_get_unsigned_secret_returns_key(sample_api_key):
    api_key = sample_api_key()
    unsigned_api_key = get_unsigned_secret(api_key.id)
    assert api_key._secret != unsigned_api_key
    assert unsigned_api_key == api_key.secret


def test_save_api_key_can_create_keys_with_same_name(
    notify_db_session,
    sample_api_key,
    sample_service,
) -> None:
    service = sample_service()

    # Create an expired API key.
    sample_api_key(
        service=service,
        key_name='normal api key',
        expired=True,
    )

    # Create an API key with the same name that is not expired
    sample_api_key(
        service=service,
        key_name='normal api key',
        expired=False,
    )

    api_key = ApiKey(
        service=service,
        name='normal api key',
        created_by=service.created_by,
        key_type=KEY_TYPE_NORMAL,
        expiry_date=datetime.utcnow() + timedelta(days=180),
    )

    # Adding a key with the same name should not raise IntegrityError. They will have unique IDs and secrets.
    save_model_api_key(api_key)

    api_keys = get_model_api_keys(service.id)

    # ensure there are 2 keys
    assert len(api_keys) == 2
    # ensure they have unique ids
    assert len(set([key.id for key in api_keys])) == 2
    # ensure the names are the same
    assert len(set([key.name for key in api_keys])) == 1

    try:
        assert api_key.expiry_date > datetime.utcnow(), 'The key should not be expired.'
        assert not api_key.revoked, 'The key should not be revoked.'
    finally:
        # Teardown
        # Clear API Key history
        ApiKeyHistory = ApiKey.get_history_model()
        stmt = delete(ApiKeyHistory).where(ApiKeyHistory.id == api_key.id)
        notify_db_session.session.execute(stmt)

        # Clear API Key
        stmt = delete(ApiKey).where(ApiKey.id == api_key.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_save_api_key_should_not_create_new_service_history(
    notify_db_session,
    sample_service,
):
    service = sample_service()

    service_history_model = Service.get_history_model()
    stmt_service = select(func.count()).select_from(service_history_model).where(service_history_model.id == service.id)

    assert notify_db_session.session.scalar(stmt_service) == 1

    api_key = ApiKey(
        **{'service': service, 'name': service.name, 'created_by': service.created_by, 'key_type': KEY_TYPE_NORMAL}
    )

    save_model_api_key(api_key)

    ApiKeyHistory = ApiKey.get_history_model()
    stmt_api_key = select(func.count()).select_from(ApiKeyHistory).where(ApiKeyHistory.id == api_key.id)

    assert notify_db_session.session.scalar(stmt_service) == 1, 'No new Service history'
    assert notify_db_session.session.scalar(stmt_api_key) == 1, 'Only one ApiKey history'


def test_save_api_key_should_generate_secret_with_expected_format(sample_service):
    service = sample_service()
    api_key = ApiKey(
        **{'service': service, 'name': service.name, 'created_by': service.created_by, 'key_type': KEY_TYPE_NORMAL}
    )
    save_model_api_key(api_key)

    assert api_key.secret is not None
    assert len(api_key.secret) >= 86


def test_save_api_key_with_uuid_generator_function_generates_uuid(notify_db_session, sample_service):
    """Test that when a UUID generator function is passed as parameter, the DAO uses it instead of the default random token generator."""
    service = sample_service()
    api_key = ApiKey(
        service=service, name='test api key with uuid secret', created_by=service.created_by, key_type=KEY_TYPE_NORMAL
    )

    # Create a mock UUID generator function that returns a predictable UUID
    test_uuid = str(uuid.uuid4())
    mock_uuid_generator = Mock(return_value=test_uuid)

    # This should fail until we implement the feature
    save_model_api_key(api_key, secret_generator=mock_uuid_generator)

    # Verify the generated secret matches the mock return value
    assert api_key.secret == test_uuid
    mock_uuid_generator.assert_called_once()


def test_save_api_key_with_custom_generator_function_uses_provided_function(notify_db_session, sample_service):
    """Test that any callable secret generator function can be used, not just UUID generation."""
    service = sample_service()
    api_key = ApiKey(
        service=service, name='test api key with custom secret', created_by=service.created_by, key_type=KEY_TYPE_NORMAL
    )

    # Create a mock custom generator function that returns a specific value
    custom_secret = 'custom-test-secret-12345'
    mock_custom_generator = Mock(return_value=custom_secret)

    save_model_api_key(api_key, secret_generator=mock_custom_generator)

    assert api_key.secret == custom_secret
    mock_custom_generator.assert_called_once()


def test_save_api_key_with_no_generator_function_maintains_default_behavior(notify_db_session, sample_service):
    """Test that existing behavior remains unchanged when no generator function is provided."""
    service = sample_service()
    api_key = ApiKey(
        service=service, name='test api key default behavior', created_by=service.created_by, key_type=KEY_TYPE_NORMAL
    )

    # Call without generator function parameter - should use existing behavior
    save_model_api_key(api_key)

    assert api_key.secret is not None
    assert len(api_key.secret) >= 86  # Current default generates ~86+ chars
    with pytest.raises(ValueError):
        uuid.UUID(api_key.secret)


def test_save_api_key_with_default_generator_function_generates_default_token(notify_db_session, sample_service):
    """Test that when a default generator function is passed as parameter, the DAO uses it to generate a default token."""
    service = sample_service()
    api_key = ApiKey(
        service=service,
        name='test api key with default secret',
        created_by=service.created_by,
        key_type=KEY_TYPE_NORMAL,
    )

    # Create a default generator function from get_secret_generator
    from app.service.rest import get_secret_generator

    default_generator = get_secret_generator(SECRET_TYPE_DEFAULT)

    save_model_api_key(api_key, secret_generator=default_generator)

    # Verify the generated secret matches default format (not UUID)
    assert api_key.secret is not None
    assert len(api_key.secret) >= 86  # Default token_urlsafe(64) generates ~86+ chars

    # Verify it's not a UUID format
    with pytest.raises(ValueError):
        uuid.UUID(api_key.secret)


@freeze_time('2025-01-01T11:00:00+00:00')
class TestUpdateApiKeyExpiry:
    @pytest.mark.parametrize('with_expiry_date', [True, False])
    def test_update_api_key_expiry(self, notify_db_session, sample_api_key, with_expiry_date):
        api_key = sample_api_key(with_expiry=with_expiry_date)
        new_expiry_date = datetime.now() + timedelta(days=30)

        update_api_key_expiry(service_id=api_key.service_id, api_key_id=api_key.id, expiry_date=new_expiry_date)

        notify_db_session.session.refresh(api_key)
        assert str(api_key.expiry_date) == str(new_expiry_date), 'The API key expiry date should be updated.'

    def test_update_api_key_expiry_throws_exception_when_key_not_found(
        self,
        notify_db_session,
        sample_api_key,
    ):
        fake_service_id = uuid.uuid4()
        api_key = sample_api_key()
        new_expiry_date = datetime.now() + timedelta(days=1)

        with pytest.raises(NoResultFound):
            update_api_key_expiry(service_id=fake_service_id, api_key_id=api_key.id, expiry_date=new_expiry_date)


def test_api_key_creation_does_not_set_automatic_expiry(sample_service):
    """Test that new API keys do not get automatic expiry dates when none is specified"""
    service = sample_service()

    # Create API key without specifying expiry_date
    api_key = ApiKey(
        service=service,
        name='test key',
        created_by=service.created_by,
        key_type=KEY_TYPE_NORMAL,
    )

    save_model_api_key(api_key)

    # Verify that expiry_date is None (no automatic expiry set)
    assert api_key.expiry_date is None, f'Expected expiry_date to be None, but got {api_key.expiry_date}'


def test_api_key_creation_respects_provided_expiry_date(sample_service):
    """Test that API key creation respects explicitly provided expiry dates"""
    service = sample_service()
    custom_expiry = datetime.utcnow() + timedelta(days=30)

    api_key = ApiKey(
        service=service,
        name='test key with custom expiry',
        created_by=service.created_by,
        key_type=KEY_TYPE_NORMAL,
        expiry_date=custom_expiry,
    )

    save_model_api_key(api_key)

    # Verify that the custom expiry date was preserved
    assert api_key.expiry_date == custom_expiry, 'Custom expiry date should be preserved'


def test_api_key_creation_validates_expiry_date_not_in_past(sample_service):
    """Test that API key creation with expiry_date in the past is handled appropriately"""
    service = sample_service()
    past_expiry = datetime.utcnow() - timedelta(days=1)  # Yesterday

    api_key = ApiKey(
        service=service,
        name='test key with past expiry',
        created_by=service.created_by,
        key_type=KEY_TYPE_NORMAL,
        expiry_date=past_expiry,
    )

    # This should still work - the validation happens at authentication time, not creation time
    save_model_api_key(api_key)

    assert api_key.expiry_date == past_expiry, 'Past expiry date should be preserved during creation'
    assert api_key.expiry_date < datetime.utcnow(), 'API key should be expired'
