import uuid

import pytest
from itsdangerous import BadSignature
from sqlalchemy.exc import SQLAlchemyError

from app import signer_bearer_token
from app.dao.service_callback_api_dao import (
    get_service_callback_api,
    get_service_delivery_status_callback_api_for_service,
    reset_service_callback_api,
    resign_service_callbacks,
    save_service_callback_api,
    suspend_unsuspend_service_callback_api,
)
from app.models import ServiceCallbackApi
from tests.app.db import create_service_callback_api
from tests.conftest import set_signer_secret_key


def test_save_service_callback_api(sample_service):
    service_callback_api = ServiceCallbackApi(
        service_id=sample_service.id,
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
    )

    save_service_callback_api(service_callback_api)

    results = ServiceCallbackApi.query.all()
    assert len(results) == 1
    callback_api = results[0]
    assert callback_api.id is not None
    assert callback_api.service_id == sample_service.id
    assert callback_api.updated_by_id == sample_service.users[0].id
    assert callback_api.url == "https://some_service/callback_endpoint"
    assert callback_api.bearer_token == "some_unique_string"
    assert callback_api._bearer_token != "some_unique_string"
    assert callback_api.updated_at is None

    versioned = ServiceCallbackApi.get_history_model().query.filter_by(id=callback_api.id).one()
    assert versioned.id == callback_api.id
    assert versioned.service_id == sample_service.id
    assert versioned.updated_by_id == sample_service.users[0].id
    assert versioned.url == "https://some_service/callback_endpoint"
    assert signer_bearer_token.verify(versioned._bearer_token) == "some_unique_string"
    assert versioned.updated_at is None
    assert versioned.version == 1


def test_save_service_callback_api_fails_if_service_does_not_exist(notify_db, notify_db_session):
    service_callback_api = ServiceCallbackApi(
        service_id=uuid.uuid4(),
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=uuid.uuid4(),
    )

    with pytest.raises(SQLAlchemyError):
        save_service_callback_api(service_callback_api)


def test_update_service_callback_api_unique_constraint(sample_service):
    service_callback_api = ServiceCallbackApi(
        service_id=sample_service.id,
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
        callback_type="delivery_status",
    )
    save_service_callback_api(service_callback_api)
    another = ServiceCallbackApi(
        service_id=sample_service.id,
        url="https://some_service/another_callback_endpoint",
        bearer_token="different_string",
        updated_by_id=sample_service.users[0].id,
        callback_type="delivery_status",
    )
    with pytest.raises(expected_exception=SQLAlchemyError):
        save_service_callback_api(another)


def test_update_service_callback_can_add_two_api_of_different_types(sample_service):
    delivery_status = ServiceCallbackApi(
        service_id=sample_service.id,
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
        callback_type="delivery_status",
    )
    save_service_callback_api(delivery_status)
    complaint = ServiceCallbackApi(
        service_id=sample_service.id,
        url="https://some_service/another_callback_endpoint",
        bearer_token="different_string",
        updated_by_id=sample_service.users[0].id,
        callback_type="complaint",
    )
    save_service_callback_api(complaint)
    results = ServiceCallbackApi.query.order_by(ServiceCallbackApi.callback_type).all()
    assert len(results) == 2
    assert results[0].serialize() == complaint.serialize()
    assert results[1].serialize() == delivery_status.serialize()


def test_update_service_callback_api(sample_service):
    service_callback_api = ServiceCallbackApi(
        service_id=sample_service.id,
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
    )

    save_service_callback_api(service_callback_api)
    results = ServiceCallbackApi.query.all()
    assert len(results) == 1
    saved_callback_api = results[0]

    reset_service_callback_api(
        saved_callback_api,
        updated_by_id=sample_service.users[0].id,
        url="https://some_service/changed_url",
    )
    updated_results = ServiceCallbackApi.query.all()
    assert len(updated_results) == 1
    updated = updated_results[0]
    assert updated.id is not None
    assert updated.service_id == sample_service.id
    assert updated.updated_by_id == sample_service.users[0].id
    assert updated.url == "https://some_service/changed_url"
    assert updated.bearer_token == "some_unique_string"
    assert updated._bearer_token != "some_unique_string"
    assert updated.updated_at is not None

    versioned_results = ServiceCallbackApi.get_history_model().query.filter_by(id=saved_callback_api.id).all()
    assert len(versioned_results) == 2
    for x in versioned_results:
        if x.version == 1:
            assert x.url == "https://some_service/callback_endpoint"
            assert not x.updated_at
        elif x.version == 2:
            assert x.url == "https://some_service/changed_url"
            assert x.updated_at
        else:
            pytest.fail("version should not exist")
        assert x.id is not None
        assert x.service_id == sample_service.id
        assert x.updated_by_id == sample_service.users[0].id
        assert signer_bearer_token.verify(x._bearer_token) == "some_unique_string"


def test_get_service_callback_api(sample_service):
    service_callback_api = ServiceCallbackApi(
        service_id=sample_service.id,
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
    )
    save_service_callback_api(service_callback_api)

    callback_api = get_service_callback_api(service_callback_api.id, sample_service.id)
    assert callback_api.id is not None
    assert callback_api.service_id == sample_service.id
    assert callback_api.updated_by_id == sample_service.users[0].id
    assert callback_api.url == "https://some_service/callback_endpoint"
    assert callback_api.bearer_token == "some_unique_string"
    assert callback_api._bearer_token != "some_unique_string"
    assert callback_api.updated_at is None


def test_get_service_delivery_status_callback_api_for_service(sample_service):
    service_callback_api = create_service_callback_api(service=sample_service)
    result = get_service_delivery_status_callback_api_for_service(sample_service.id)
    assert result.id == service_callback_api.id
    assert result.url == service_callback_api.url
    assert result.bearer_token == service_callback_api.bearer_token
    assert result.created_at == service_callback_api.created_at
    assert result.updated_at == service_callback_api.updated_at
    assert result.updated_by_id == service_callback_api.updated_by_id


class TestResigning:
    @pytest.mark.parametrize("resign", [True, False])
    def test_resign_callbacks_resigns_or_previews(self, resign, sample_service):
        from app import signer_bearer_token

        with set_signer_secret_key(signer_bearer_token, ["k1", "k2"]):
            initial_callback = create_service_callback_api(service=sample_service)
            bearer_token = initial_callback.bearer_token
            _bearer_token = initial_callback._bearer_token

        with set_signer_secret_key(signer_bearer_token, ["k2", "k3"]):
            resign_service_callbacks(resign=resign)
            callback = ServiceCallbackApi.query.get(initial_callback.id)
            assert callback.bearer_token == bearer_token  # unsigned value is the same
            if resign:
                assert callback._bearer_token != _bearer_token  # signature is different
            else:
                assert callback._bearer_token == _bearer_token  # signature is the same

    def test_resign_callbacks_fails_if_cannot_verify_signatures(self, sample_service):
        from app import signer_bearer_token

        with set_signer_secret_key(signer_bearer_token, ["k1", "k2"]):
            create_service_callback_api(service=sample_service)

        with set_signer_secret_key(signer_bearer_token, ["k3"]):
            with pytest.raises(BadSignature):
                resign_service_callbacks(resign=True)

    def test_resign_callbacks_unsafe_resigns_with_new_key(self, sample_service):
        from app import signer_bearer_token

        with set_signer_secret_key(signer_bearer_token, ["k1", "k2"]):
            initial_callback = create_service_callback_api(service=sample_service)
            bearer_token = initial_callback.bearer_token
            _bearer_token = initial_callback._bearer_token

        with set_signer_secret_key(signer_bearer_token, ["k3"]):
            resign_service_callbacks(resign=True, unsafe=True)
            callback = ServiceCallbackApi.query.get(initial_callback.id)
            assert callback.bearer_token == bearer_token  # unsigned value is the same
            assert callback._bearer_token != _bearer_token  # signature is different


class TestSuspendedServiceCallback:
    def test_update_service_callback_api(self, sample_service):
        service_callback_api = ServiceCallbackApi(
            service_id=sample_service.id,
            url="https://some_service/callback_endpoint",
            bearer_token="some_unique_string",
            updated_by_id=sample_service.users[0].id,
        )

        save_service_callback_api(service_callback_api)
        results = ServiceCallbackApi.query.all()
        assert len(results) == 1
        saved_callback_api = results[0]

        suspend_unsuspend_service_callback_api(
            saved_callback_api,
            updated_by_id=sample_service.users[0].id,
            suspend=True,
        )
        updated_results = ServiceCallbackApi.query.all()
        assert len(updated_results) == 1
        updated = updated_results[0]
        assert updated.id is not None
        assert updated.service_id == sample_service.id
        assert updated.updated_by_id == sample_service.users[0].id
        assert updated.url == "https://some_service/callback_endpoint"
        assert updated.bearer_token == "some_unique_string"
        assert updated._bearer_token != "some_unique_string"
        assert updated.updated_at is not None
        assert updated.is_suspended is True
        assert updated.suspended_at is not None

        versioned_results = ServiceCallbackApi.get_history_model().query.filter_by(id=saved_callback_api.id).all()
        assert len(versioned_results) == 2
        for x in versioned_results:
            if x.version == 1:
                assert x.is_suspended is None
            elif x.version == 2:
                assert x.is_suspended is True
            else:
                pytest.fail("version should not exist")
            assert x.id is not None
            assert x.service_id == sample_service.id
            assert x.updated_by_id == sample_service.users[0].id
            assert signer_bearer_token.verify(x._bearer_token) == "some_unique_string"
