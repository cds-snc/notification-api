from datetime import datetime, timedelta

import pytest
from itsdangerous import BadSignature
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound

from app.dao.api_key_dao import (
    expire_api_key,
    get_api_key_by_secret,
    get_model_api_keys,
    get_unsigned_secret,
    get_unsigned_secrets,
    resign_api_keys,
    save_model_api_key,
    update_compromised_api_key_info,
)
from app.models import KEY_TYPE_NORMAL, ApiKey
from tests.app.db import create_api_key
from tests.conftest import set_signer_secret_key


def test_save_api_key_should_create_new_api_key_and_history(sample_service):
    api_key = ApiKey(
        **{
            "service": sample_service,
            "name": sample_service.name,
            "created_by": sample_service.created_by,
            "key_type": KEY_TYPE_NORMAL,
        }
    )
    save_model_api_key(api_key)

    all_api_keys = get_model_api_keys(service_id=sample_service.id)
    assert len(all_api_keys) == 1
    assert all_api_keys[0] == api_key
    assert api_key.version == 1
    assert api_key.last_used_timestamp is None

    all_history = api_key.get_history_model().query.all()
    assert len(all_history) == 1
    assert all_history[0].id == api_key.id
    assert all_history[0].version == api_key.version


def test_expire_api_key_should_update_the_api_key_and_create_history_record(notify_api, sample_api_key):
    expire_api_key(service_id=sample_api_key.service_id, api_key_id=sample_api_key.id)
    all_api_keys = get_model_api_keys(service_id=sample_api_key.service_id)
    assert len(all_api_keys) == 1
    assert all_api_keys[0].expiry_date <= datetime.utcnow()
    assert all_api_keys[0].secret == sample_api_key.secret
    assert all_api_keys[0].id == sample_api_key.id
    assert all_api_keys[0].service_id == sample_api_key.service_id

    all_history = sample_api_key.get_history_model().query.all()
    assert len(all_history) == 2
    assert all_history[0].id == sample_api_key.id
    assert all_history[1].id == sample_api_key.id
    sorted_all_history = sorted(all_history, key=lambda hist: hist.version)
    sorted_all_history[0].version = 1
    sorted_all_history[1].version = 2


def test_update_compromised_api_key_info_and_create_history_record(notify_api, sample_api_key):
    update_compromised_api_key_info(
        service_id=sample_api_key.service_id, api_key_id=sample_api_key.id, compromised_info={"key": "value"}
    )
    all_api_keys = get_model_api_keys(service_id=sample_api_key.service_id)
    assert len(all_api_keys) == 1
    assert all_api_keys[0].secret == sample_api_key.secret
    assert all_api_keys[0].id == sample_api_key.id
    assert all_api_keys[0].service_id == sample_api_key.service_id
    assert all_api_keys[0].compromised_key_info == {"key": "value"}

    all_history = sample_api_key.get_history_model().query.all()
    assert len(all_history) == 2
    assert all_history[0].id == sample_api_key.id
    assert all_history[1].id == sample_api_key.id
    sorted_all_history = sorted(all_history, key=lambda hist: hist.version)
    sorted_all_history[0].version = 1
    sorted_all_history[1].version = 2


def test_get_api_key_should_raise_exception_when_api_key_does_not_exist(sample_service, fake_uuid):
    with pytest.raises(NoResultFound):
        get_model_api_keys(sample_service.id, id=fake_uuid)


def test_should_return_api_key_for_service(notify_api, notify_db, notify_db_session, sample_api_key):
    api_key = get_model_api_keys(service_id=sample_api_key.service_id, id=sample_api_key.id)
    assert api_key == sample_api_key


def test_should_return_unsigned_api_keys_for_service_id(sample_api_key):
    unsigned_api_key = get_unsigned_secrets(sample_api_key.service_id)
    assert len(unsigned_api_key) == 1
    assert sample_api_key._secret != unsigned_api_key[0]
    assert unsigned_api_key[0] == sample_api_key.secret


def test_get_unsigned_secret_returns_key(sample_api_key):
    unsigned_api_key = get_unsigned_secret(sample_api_key.id)
    assert sample_api_key._secret != unsigned_api_key
    assert unsigned_api_key == sample_api_key.secret


def test_get_api_key_by_secret(sample_api_key):
    unsigned_secret = get_unsigned_secret(sample_api_key.id)
    assert get_api_key_by_secret(unsigned_secret).id == sample_api_key.id

    with pytest.raises(NoResultFound):
        get_api_key_by_secret("nope")


def test_should_not_allow_duplicate_key_names_per_service(sample_api_key, fake_uuid):
    api_key = ApiKey(
        **{
            "id": fake_uuid,
            "service": sample_api_key.service,
            "name": sample_api_key.name,
            "created_by": sample_api_key.created_by,
            "key_type": KEY_TYPE_NORMAL,
        }
    )
    with pytest.raises(IntegrityError):
        save_model_api_key(api_key)


def test_save_api_key_can_create_key_with_same_name_if_other_is_expired(sample_service):
    expired_api_key = ApiKey(
        **{
            "service": sample_service,
            "name": "normal api key",
            "created_by": sample_service.created_by,
            "key_type": KEY_TYPE_NORMAL,
            "expiry_date": datetime.utcnow(),
        }
    )
    save_model_api_key(expired_api_key)
    api_key = ApiKey(
        **{
            "service": sample_service,
            "name": "normal api key",
            "created_by": sample_service.created_by,
            "key_type": KEY_TYPE_NORMAL,
        }
    )
    save_model_api_key(api_key)
    keys = ApiKey.query.all()
    assert len(keys) == 2


def test_save_api_key_should_not_create_new_service_history(sample_service):
    from app.models import Service

    assert Service.query.count() == 1
    assert Service.get_history_model().query.count() == 1

    api_key = ApiKey(
        **{
            "service": sample_service,
            "name": sample_service.name,
            "created_by": sample_service.created_by,
            "key_type": KEY_TYPE_NORMAL,
        }
    )
    save_model_api_key(api_key)

    assert Service.get_history_model().query.count() == 1


@pytest.mark.parametrize("days_old, expected_length", [(5, 1), (8, 0)])
def test_should_not_return_revoked_api_keys_older_than_7_days(sample_service, days_old, expected_length):
    expired_api_key = ApiKey(
        **{
            "service": sample_service,
            "name": sample_service.name,
            "created_by": sample_service.created_by,
            "key_type": KEY_TYPE_NORMAL,
            "expiry_date": datetime.utcnow() - timedelta(days=days_old),
        }
    )
    save_model_api_key(expired_api_key)

    all_api_keys = get_model_api_keys(service_id=sample_service.id)

    assert len(all_api_keys) == expected_length


class TestResigning:
    @pytest.mark.parametrize("resign", [True, False])
    def test_resign_api_keys_resigns_or_previews(self, resign, sample_service):
        from app import signer_api_key

        with set_signer_secret_key(signer_api_key, ["k1", "k2"]):
            initial_key = create_api_key(service=sample_service)
            secret = initial_key.secret
            _secret = initial_key._secret

        with set_signer_secret_key(signer_api_key, ["k2", "k3"]):
            resign_api_keys(resign=resign)
            api_key = ApiKey.query.get(initial_key.id)
            assert api_key.secret == secret  # unsigned value is the same
            if resign:
                assert api_key._secret != _secret  # signature is different
            else:
                assert api_key._secret == _secret  # signature is the same

    def test_resign_api_keys_fails_if_cannot_verify_signatures(self, sample_service):
        from app import signer_api_key

        with set_signer_secret_key(signer_api_key, ["k1", "k2"]):
            create_api_key(service=sample_service)

        with set_signer_secret_key(signer_api_key, "k3"):
            with pytest.raises(BadSignature):
                resign_api_keys(resign=True)

    def test_resign_api_keys_unsafe_resigns_with_new_key(self, sample_service):
        from app import signer_api_key

        with set_signer_secret_key(signer_api_key, ["k1", "k2"]):
            initial_key = create_api_key(service=sample_service)
            secret = initial_key.secret
            _secret = initial_key._secret

        with set_signer_secret_key(signer_api_key, ["k3"]):
            resign_api_keys(resign=True, unsafe=True)
            api_key = ApiKey.query.get(initial_key.id)
            assert api_key.secret == secret  # unsigned value is the same
            assert api_key._secret != _secret  # signature is different
