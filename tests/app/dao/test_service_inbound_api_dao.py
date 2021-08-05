import uuid

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import encryption
from app.dao.service_inbound_api_dao import (
    get_service_inbound_api,
    get_service_inbound_api_for_service,
    reset_service_inbound_api,
    save_service_inbound_api,
)
from app.models import ServiceInboundApi
from tests.app.db import create_service_inbound_api


def test_save_service_inbound_api(sample_service):
    service_inbound_api = ServiceInboundApi(
        service_id=sample_service.id,
        url="https://some_service/inbound_messages",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
    )

    save_service_inbound_api(service_inbound_api)

    results = ServiceInboundApi.query.all()
    assert len(results) == 1
    inbound_api = results[0]
    assert inbound_api.id is not None
    assert inbound_api.service_id == sample_service.id
    assert inbound_api.updated_by_id == sample_service.users[0].id
    assert inbound_api.url == "https://some_service/inbound_messages"
    assert inbound_api.bearer_token == "some_unique_string"
    assert inbound_api._bearer_token != "some_unique_string"
    assert inbound_api.updated_at is None

    versioned = ServiceInboundApi.get_history_model().query.filter_by(id=inbound_api.id).one()
    assert versioned.id == inbound_api.id
    assert versioned.service_id == sample_service.id
    assert versioned.updated_by_id == sample_service.users[0].id
    assert versioned.url == "https://some_service/inbound_messages"
    assert encryption.decrypt(versioned._bearer_token) == "some_unique_string"
    assert versioned.updated_at is None
    assert versioned.version == 1


def test_save_service_inbound_api_fails_if_service_does_not_exist(notify_db, notify_db_session):
    service_inbound_api = ServiceInboundApi(
        service_id=uuid.uuid4(),
        url="https://some_service/inbound_messages",
        bearer_token="some_unique_string",
        updated_by_id=uuid.uuid4(),
    )

    with pytest.raises(SQLAlchemyError):
        save_service_inbound_api(service_inbound_api)


def test_update_service_inbound_api(sample_service):
    service_inbound_api = ServiceInboundApi(
        service_id=sample_service.id,
        url="https://some_service/inbound_messages",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
    )

    save_service_inbound_api(service_inbound_api)
    results = ServiceInboundApi.query.all()
    assert len(results) == 1
    saved_inbound_api = results[0]

    reset_service_inbound_api(
        saved_inbound_api,
        updated_by_id=sample_service.users[0].id,
        url="https://some_service/changed_url",
    )
    updated_results = ServiceInboundApi.query.all()
    assert len(updated_results) == 1
    updated = updated_results[0]
    assert updated.id is not None
    assert updated.service_id == sample_service.id
    assert updated.updated_by_id == sample_service.users[0].id
    assert updated.url == "https://some_service/changed_url"
    assert updated.bearer_token == "some_unique_string"
    assert updated._bearer_token != "some_unique_string"
    assert updated.updated_at is not None

    versioned_results = ServiceInboundApi.get_history_model().query.filter_by(id=saved_inbound_api.id).all()
    assert len(versioned_results) == 2
    for x in versioned_results:
        if x.version == 1:
            assert x.url == "https://some_service/inbound_messages"
            assert not x.updated_at
        elif x.version == 2:
            assert x.url == "https://some_service/changed_url"
            assert x.updated_at
        else:
            pytest.fail("version should not exist")
        assert x.id is not None
        assert x.service_id == sample_service.id
        assert x.updated_by_id == sample_service.users[0].id
        assert encryption.decrypt(x._bearer_token) == "some_unique_string"


def test_get_service_inbound_api(sample_service):
    service_inbound_api = ServiceInboundApi(
        service_id=sample_service.id,
        url="https://some_service/inbound_messages",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
    )
    save_service_inbound_api(service_inbound_api)

    inbound_api = get_service_inbound_api(service_inbound_api.id, sample_service.id)
    assert inbound_api.id is not None
    assert inbound_api.service_id == sample_service.id
    assert inbound_api.updated_by_id == sample_service.users[0].id
    assert inbound_api.url == "https://some_service/inbound_messages"
    assert inbound_api.bearer_token == "some_unique_string"
    assert inbound_api._bearer_token != "some_unique_string"
    assert inbound_api.updated_at is None


def test_get_service_inbound_api_for_service(sample_service):
    service_inbound_api = create_service_inbound_api(service=sample_service)
    result = get_service_inbound_api_for_service(sample_service.id)
    assert result.id == service_inbound_api.id
    assert result.url == service_inbound_api.url
    assert result.bearer_token == service_inbound_api.bearer_token
    assert result.created_at == service_inbound_api.created_at
    assert result.updated_at == service_inbound_api.updated_at
    assert result.updated_by_id == service_inbound_api.updated_by_id
