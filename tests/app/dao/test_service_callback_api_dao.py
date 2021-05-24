import uuid

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import encryption
from app.dao.service_callback_api_dao import (
    save_service_callback_api,
    reset_service_callback_api,
    get_service_callback_api,
    get_service_delivery_status_callback_api_for_service)
from app.models import ServiceCallbackApi, NOTIFICATION_FAILED, NOTIFICATION_TEMPORARY_FAILURE, \
    NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_STATUS_TYPES_COMPLETED, NOTIFICATION_SENT, NOTIFICATION_DELIVERED
from app.schemas import service_callback_api_schema
from tests.app.db import create_service_callback_api


def test_save_service_callback_api(sample_service):
    notification_statuses = [NOTIFICATION_FAILED]
    service_callback_api = ServiceCallbackApi(  # nosec
        service_id=sample_service.id,
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
        notification_statuses=notification_statuses
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
    assert callback_api.notification_statuses == notification_statuses

    versioned = ServiceCallbackApi.get_history_model().query.filter_by(id=callback_api.id).one()
    assert versioned.id == callback_api.id
    assert versioned.service_id == sample_service.id
    assert versioned.updated_by_id == sample_service.users[0].id
    assert versioned.url == "https://some_service/callback_endpoint"
    assert encryption.decrypt(versioned._bearer_token) == "some_unique_string"
    assert versioned.updated_at is None
    assert versioned.version == 1


def test_save_service_callback_api_fails_if_service_does_not_exist(notify_db, notify_db_session):
    notification_statuses = [NOTIFICATION_FAILED]
    service_callback_api = ServiceCallbackApi(  # nosec
        service_id=uuid.uuid4(),
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=uuid.uuid4(),
        notification_statuses=str(notification_statuses)
    )

    with pytest.raises(SQLAlchemyError):
        save_service_callback_api(service_callback_api)


def test_update_service_callback_api_unique_constraint(sample_service):
    notification_statuses = [NOTIFICATION_FAILED]
    service_callback_api = ServiceCallbackApi(  # nosec
        service_id=sample_service.id,
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
        callback_type='delivery_status',
        notification_statuses=str(notification_statuses)
    )
    save_service_callback_api(service_callback_api)
    another = ServiceCallbackApi(  # nosec
        service_id=sample_service.id,
        url="https://some_service/another_callback_endpoint",
        bearer_token="different_string",
        updated_by_id=sample_service.users[0].id,
        callback_type='delivery_status',
        notification_statuses=str(notification_statuses)
    )
    with pytest.raises(expected_exception=SQLAlchemyError):
        save_service_callback_api(another)


def test_update_service_callback_can_add_two_api_of_different_types(sample_service):
    notification_statuses = [NOTIFICATION_FAILED]
    delivery_status = ServiceCallbackApi(  # nosec
        service_id=sample_service.id,
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
        callback_type='delivery_status',
        notification_statuses=str(notification_statuses)
    )
    save_service_callback_api(delivery_status)
    complaint = ServiceCallbackApi(  # nosec
        service_id=sample_service.id,
        url="https://some_service/another_callback_endpoint",
        bearer_token="different_string",
        updated_by_id=sample_service.users[0].id,
        callback_type='complaint',
        notification_statuses=str(notification_statuses)
    )
    save_service_callback_api(complaint)
    results = ServiceCallbackApi.query.order_by(ServiceCallbackApi.callback_type).all()
    assert len(results) == 2

    results0_dump = service_callback_api_schema.dump(results[0]).data
    results1_dump = service_callback_api_schema.dump(results[1]).data

    assert results0_dump == service_callback_api_schema.dump(complaint).data
    assert results1_dump == service_callback_api_schema.dump(delivery_status).data


def test_update_service_callback_api(sample_service):
    notification_statuses = [NOTIFICATION_FAILED]
    service_callback_api = ServiceCallbackApi(  # nosec
        service_id=sample_service.id,
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
        notification_statuses=str(notification_statuses)
    )

    save_service_callback_api(service_callback_api)
    results = ServiceCallbackApi.query.all()
    assert len(results) == 1
    saved_callback_api = results[0]

    reset_service_callback_api(saved_callback_api, updated_by_id=sample_service.users[0].id,
                               url="https://some_service/changed_url")
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
        assert encryption.decrypt(x._bearer_token) == "some_unique_string"


def test_get_service_callback_api(sample_service):
    notification_statuses = [NOTIFICATION_FAILED]
    service_callback_api = ServiceCallbackApi(  # nosec
        service_id=sample_service.id,
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
        notification_statuses=notification_statuses
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
    result = get_service_delivery_status_callback_api_for_service(sample_service.id, 'delivered')
    assert result.id == service_callback_api.id
    assert result.url == service_callback_api.url
    assert result.bearer_token == service_callback_api.bearer_token
    assert result.created_at == service_callback_api.created_at
    assert result.updated_at == service_callback_api.updated_at
    assert result.updated_by_id == service_callback_api.updated_by_id


@pytest.mark.parametrize('notification_statuses', [
    [NOTIFICATION_FAILED],
    [NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_FAILED, NOTIFICATION_TEMPORARY_FAILURE],
    [NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_FAILED],
])
def test_existing_service_delivery_status_callback_api_by_status(sample_service, notification_statuses):
    service_callback_api = create_service_callback_api(
        service=sample_service, notification_statuses=notification_statuses
    )

    for notification_status in notification_statuses:
        result = get_service_delivery_status_callback_api_for_service(
            sample_service.id,
            notification_status=notification_status
        )
        assert result.id == service_callback_api.id
        assert result.url == service_callback_api.url
        assert result.bearer_token == service_callback_api.bearer_token
        assert result.created_at == service_callback_api.created_at
        assert result.updated_at == service_callback_api.updated_at
        assert result.updated_by_id == service_callback_api.updated_by_id


@pytest.mark.parametrize('saved_notification_statuses, query_notification_statuses', [
    (
        [NOTIFICATION_FAILED],
        list(filter(lambda status: status != NOTIFICATION_FAILED, NOTIFICATION_STATUS_TYPES_COMPLETED))
    ),
    (
        [NOTIFICATION_SENT, NOTIFICATION_DELIVERED],
        [NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_TEMPORARY_FAILURE, NOTIFICATION_FAILED]
    ),
    (
        [NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_FAILED],
        [NOTIFICATION_SENT, NOTIFICATION_DELIVERED]
    ),
])
def test_no_service_delivery_status_callback_api_by_status(
        sample_service, saved_notification_statuses, query_notification_statuses
):
    create_service_callback_api(
        service=sample_service, notification_statuses=saved_notification_statuses
    )
    for notification_status in query_notification_statuses:
        result = get_service_delivery_status_callback_api_for_service(
            sample_service.id,
            notification_status=notification_status
        )
        assert result is None
