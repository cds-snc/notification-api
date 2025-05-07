import uuid

import pytest
from sqlalchemy import select, Table
from sqlalchemy.exc import SQLAlchemyError

from app import encryption
from app.constants import (
    NOTIFICATION_FAILED,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_STATUS_TYPES_COMPLETED,
    NOTIFICATION_SENT,
    NOTIFICATION_DELIVERED,
    WEBHOOK_CHANNEL_TYPE,
)
from app.dao.service_callback_api_dao import (
    save_service_callback_api,
    reset_service_callback_api,
    get_service_callback,
    get_service_delivery_status_callback_api_for_service,
)
from app.db import db
from app.models import ServiceCallback
from app.schemas import service_callback_api_schema
from tests.app.db import create_service_callback_api


def test_save_service_callback_api(
    notify_db_session,
    sample_service,
):
    notification_statuses = [NOTIFICATION_FAILED]
    service = sample_service()

    service_callback_obj = ServiceCallback(  # nosec
        service_id=service.id,
        url='https://some_service/callback_endpoint',
        bearer_token='some_unique_string',
        updated_by_id=service.users[0].id,
        notification_statuses=notification_statuses,
        callback_channel=WEBHOOK_CHANNEL_TYPE,
    )

    save_service_callback_api(service_callback_obj)

    callback_api = notify_db_session.session.get(ServiceCallback, service_callback_obj.id)

    assert callback_api is not None
    assert callback_api.id == service_callback_obj.id
    assert callback_api.service_id == service_callback_obj.service_id
    assert callback_api.updated_by_id == service_callback_obj.updated_by_id
    assert callback_api.url == 'https://some_service/callback_endpoint'
    assert callback_api.bearer_token == 'some_unique_string'
    assert callback_api._bearer_token != 'some_unique_string'
    assert callback_api.updated_at is None
    assert callback_api.notification_statuses == notification_statuses

    ServiceCallbackHistory = Table(
        'service_callback_history', ServiceCallback.get_history_model().metadata, autoload_with=db.engine
    )

    stmt = select(ServiceCallbackHistory).where(ServiceCallbackHistory.c.id == callback_api.id)
    versioned = notify_db_session.session.execute(stmt).one()

    assert versioned.id == callback_api.id
    assert versioned.service_id == service.id
    assert versioned.updated_by_id == service.users[0].id
    assert versioned.url == 'https://some_service/callback_endpoint'
    assert encryption.decrypt(versioned.bearer_token) == 'some_unique_string'
    assert versioned.updated_at is None
    assert versioned.version == 1

    # Teardown
    # sample_service cleans up ServiceCallbacks and histories


def test_save_service_callback_api_fails_if_service_does_not_exist(notify_api):
    notification_statuses = [NOTIFICATION_FAILED]
    service_callback_api = ServiceCallback(  # nosec
        service_id=uuid.uuid4(),
        url='https://some_service/callback_endpoint',
        bearer_token='some_unique_string',
        updated_by_id=uuid.uuid4(),
        notification_statuses=str(notification_statuses),
        callback_channel=WEBHOOK_CHANNEL_TYPE,
    )

    with pytest.raises(SQLAlchemyError):
        save_service_callback_api(service_callback_api)


def test_update_service_callback_api_unique_constraint(
    sample_service,
):
    service = sample_service()
    notification_statuses = [NOTIFICATION_FAILED]
    service_callback_api = ServiceCallback(  # nosec
        service_id=service.id,
        url='https://some_service/callback_endpoint',
        bearer_token='some_unique_string',
        updated_by_id=service.users[0].id,
        callback_type='delivery_status',
        notification_statuses=str(notification_statuses),
        callback_channel=WEBHOOK_CHANNEL_TYPE,
    )
    save_service_callback_api(service_callback_api)
    another = ServiceCallback(  # nosec
        service_id=service.id,
        url='https://some_service/another_callback_endpoint',
        bearer_token='different_string',
        updated_by_id=service.users[0].id,
        callback_type='delivery_status',
        notification_statuses=str(notification_statuses),
        callback_channel=WEBHOOK_CHANNEL_TYPE,
    )
    with pytest.raises(expected_exception=SQLAlchemyError):
        save_service_callback_api(another)


def test_update_service_callback_can_add_two_api_of_different_types(
    notify_db_session,
    sample_service,
):
    service = sample_service()
    notification_statuses = [NOTIFICATION_FAILED]
    delivery_status = ServiceCallback(  # nosec
        service_id=service.id,
        url='https://some_service/callback_endpoint',
        bearer_token='some_unique_string',
        updated_by_id=service.users[0].id,
        callback_type='delivery_status',
        notification_statuses=str(notification_statuses),
        callback_channel=WEBHOOK_CHANNEL_TYPE,
    )
    save_service_callback_api(delivery_status)
    complaint = ServiceCallback(  # nosec
        service_id=service.id,
        url='https://some_service/another_callback_endpoint',
        bearer_token='different_string',
        updated_by_id=service.users[0].id,
        callback_type='complaint',
        callback_channel=WEBHOOK_CHANNEL_TYPE,
    )
    save_service_callback_api(complaint)
    stmt = (
        select(ServiceCallback).where(ServiceCallback.service_id == service.id).order_by(ServiceCallback.callback_type)
    )
    results = notify_db_session.session.scalars(stmt).all()
    assert len(results) == 2

    results0_dump = service_callback_api_schema.dump(results[0])
    results1_dump = service_callback_api_schema.dump(results[1])

    assert results0_dump == service_callback_api_schema.dump(complaint)
    assert results1_dump == service_callback_api_schema.dump(delivery_status)


def test_update_service_callback_api(
    notify_db_session,
    sample_service,
):
    service = sample_service()
    notification_statuses = [NOTIFICATION_FAILED]
    service_callback_api = ServiceCallback(  # nosec
        service_id=service.id,
        url='https://some_service/callback_endpoint',
        bearer_token='some_unique_string',
        updated_by_id=service.users[0].id,
        notification_statuses=str(notification_statuses),
        callback_channel=WEBHOOK_CHANNEL_TYPE,
    )

    save_service_callback_api(service_callback_api)
    saved_callback_api = notify_db_session.session.get(ServiceCallback, service_callback_api.id)
    assert saved_callback_api

    reset_service_callback_api(
        saved_callback_api, updated_by_id=service.users[0].id, url='https://some_service/changed_url'
    )

    stmt = select(ServiceCallback).where(ServiceCallback.service_id == service.id)
    updated_results = notify_db_session.session.scalars(stmt).all()
    assert len(updated_results) == 1
    updated = updated_results[0]
    assert updated.id is not None
    assert updated.service_id == service.id
    assert updated.updated_by_id == service.users[0].id
    assert updated.url == 'https://some_service/changed_url'
    assert updated.bearer_token == 'some_unique_string'
    assert updated._bearer_token != 'some_unique_string'
    assert updated.updated_at is not None

    history_model = ServiceCallback.get_history_model()
    stmt = select(history_model).where(history_model.id == saved_callback_api.id)
    versioned_results = notify_db_session.session.scalars(stmt).all()

    assert len(versioned_results) == 2
    for x in versioned_results:
        if x.version == 1:
            assert x.url == 'https://some_service/callback_endpoint'
            assert not x.updated_at
        elif x.version == 2:
            assert x.url == 'https://some_service/changed_url'
            assert x.updated_at
        else:
            pytest.fail('version should not exist')
        assert x.id is not None
        assert x.service_id == service.id
        assert x.updated_by_id == service.users[0].id
        assert encryption.decrypt(x._bearer_token) == 'some_unique_string'


@pytest.mark.parametrize('payload_included', [True, False])
def test_get_service_callback(
    sample_service,
    payload_included,
):
    service = sample_service()
    notification_statuses = [NOTIFICATION_FAILED]
    service_callback = ServiceCallback(  # nosec
        service_id=service.id,
        url='https://some_service/callback_endpoint',
        bearer_token='some_unique_string',
        updated_by_id=service.users[0].id,
        notification_statuses=notification_statuses,
        callback_channel=WEBHOOK_CHANNEL_TYPE,
        include_provider_payload=payload_included,
    )

    save_service_callback_api(service_callback)
    service_callback = get_service_callback(service_callback.id)

    assert service_callback.id is not None
    assert service_callback.service_id == str(service.id)
    assert service_callback.url == 'https://some_service/callback_endpoint'
    assert encryption.decrypt(service_callback._bearer_token) == 'some_unique_string'

    if payload_included:
        assert service_callback.include_provider_payload
    else:
        assert not service_callback.include_provider_payload


def test_get_service_delivery_status_callback_api_for_service(sample_service):
    service = sample_service()
    service_callback_api = create_service_callback_api(service=service)
    result = get_service_delivery_status_callback_api_for_service(service.id, 'delivered')
    assert result.id == str(service_callback_api.id)
    assert result.url == service_callback_api.url
    assert result._bearer_token == service_callback_api._bearer_token
    assert result.include_provider_payload == service_callback_api.include_provider_payload
    assert result.callback_type == service_callback_api.callback_type


@pytest.mark.parametrize(
    'notification_statuses',
    [
        [NOTIFICATION_FAILED],
        [NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_FAILED, NOTIFICATION_TEMPORARY_FAILURE],
        [NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_FAILED],
    ],
)
def test_existing_service_delivery_status_callback_api_by_status(
    sample_service,
    notification_statuses,
):
    service = sample_service()
    service_callback_api = create_service_callback_api(service=service, notification_statuses=notification_statuses)

    for notification_status in notification_statuses:
        result = get_service_delivery_status_callback_api_for_service(
            service.id, notification_status=notification_status
        )
        assert result.id == str(service_callback_api.id)
        assert result.url == service_callback_api.url
        assert result._bearer_token == service_callback_api._bearer_token
        assert result.include_provider_payload == service_callback_api.include_provider_payload
        assert result.callback_type == service_callback_api.callback_type


@pytest.mark.parametrize(
    'saved_notification_statuses, query_notification_statuses',
    [
        (
            [NOTIFICATION_FAILED],
            list(filter(lambda status: status != NOTIFICATION_FAILED, NOTIFICATION_STATUS_TYPES_COMPLETED)),
        ),
        (
            [NOTIFICATION_SENT, NOTIFICATION_DELIVERED],
            [NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_TEMPORARY_FAILURE, NOTIFICATION_FAILED],
        ),
        ([NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_FAILED], [NOTIFICATION_SENT, NOTIFICATION_DELIVERED]),
    ],
)
def test_no_service_delivery_status_callback_api_by_status(
    sample_service,
    saved_notification_statuses,
    query_notification_statuses,
):
    service = sample_service()
    create_service_callback_api(service=service, notification_statuses=saved_notification_statuses)
    for notification_status in query_notification_statuses:
        result = get_service_delivery_status_callback_api_for_service(
            service.id, notification_status=notification_status
        )
        assert result is None
