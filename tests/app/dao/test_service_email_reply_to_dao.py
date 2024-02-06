import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.dao.service_email_reply_to_dao import (
    add_reply_to_email_address_for_service,
    archive_reply_to_email_address,
    dao_get_reply_to_by_id,
    dao_get_reply_to_by_service_id,
    update_reply_to_email_address,
)
from app.errors import InvalidRequest
from app.exceptions import ArchiveValidationError
from app.models import ServiceEmailReplyTo
from tests.app.db import create_reply_to_email


def test_dao_get_reply_to_by_service_id(sample_service):
    service = sample_service(email_address=None)
    default_reply_to = create_reply_to_email(service=service, email_address='something@email.com')
    second_reply_to = create_reply_to_email(service=service, email_address='second@email.com', is_default=False)
    another_reply_to = create_reply_to_email(service=service, email_address='another@email.com', is_default=False)

    results = dao_get_reply_to_by_service_id(service_id=service.id)

    assert len(results) == 3
    assert default_reply_to == results[0]
    assert another_reply_to == results[1]
    assert second_reply_to == results[2]


def test_dao_get_reply_to_by_service_id_does_not_return_archived_reply_tos(sample_service):
    service = sample_service(email_address=None)
    create_reply_to_email(service=service, email_address='something@email.com')
    create_reply_to_email(service=service, email_address='another@email.com', is_default=False)
    archived_reply_to = create_reply_to_email(
        service=service, email_address='second@email.com', is_default=False, archived=True
    )

    results = dao_get_reply_to_by_service_id(service_id=service.id)

    assert len(results) == 2
    assert archived_reply_to not in results


def test_add_reply_to_email_address_for_service_creates_first_email_for_service(sample_service):
    service = sample_service(email_address=None)
    add_reply_to_email_address_for_service(service_id=service.id, email_address='new@address.com', is_default=True)

    results = dao_get_reply_to_by_service_id(service_id=service.id)
    assert len(results) == 1
    assert results[0].email_address == 'new@address.com'
    assert results[0].is_default
    assert not results[0].archived


def test_add_reply_to_email_address_for_service_creates_another_email_for_service(sample_service):
    service = sample_service(email_address=None)
    create_reply_to_email(service=service, email_address='first@address.com')

    add_reply_to_email_address_for_service(service_id=service.id, email_address='second@address.com', is_default=False)

    results = dao_get_reply_to_by_service_id(service_id=service.id)
    assert len(results) == 2
    for x in results:
        if x.email_address == 'first@address.com':
            assert x.is_default
        elif x.email_address == 'second@address.com':
            assert not x.is_default
        else:
            assert False


def test_add_reply_to_email_address_new_reply_to_is_default_existing_reply_to_is_not(sample_service):
    service = sample_service(email_address=None)
    create_reply_to_email(service=service, email_address='first@address.com', is_default=True)
    add_reply_to_email_address_for_service(service_id=service.id, email_address='second@address.com', is_default=True)

    results = dao_get_reply_to_by_service_id(service_id=service.id)
    assert len(results) == 2
    for x in results:
        if x.email_address == 'first@address.com':
            assert not x.is_default
        elif x.email_address == 'second@address.com':
            assert x.is_default
        else:
            assert False


def test_add_reply_to_email_address_can_add_a_third_reply_to_address(sample_service):
    service = sample_service(email_address=None)
    add_reply_to_email_address_for_service(service_id=service.id, email_address='first@address.com', is_default=True)
    add_reply_to_email_address_for_service(service_id=service.id, email_address='second@address.com', is_default=False)
    add_reply_to_email_address_for_service(service_id=service.id, email_address='third@address.com', is_default=False)

    results = dao_get_reply_to_by_service_id(service_id=service.id)
    assert len(results) == 3

    for x in results:
        if x.email_address == 'first@address.com':
            assert x.is_default
        elif x.email_address == 'second@address.com':
            assert not x.is_default
        elif x.email_address == 'third@address.com':
            assert not x.is_default
        else:
            assert False


def test_add_reply_to_email_address_ensures_first_reply_to_is_default(sample_service):
    service = sample_service(email_address=None)
    with pytest.raises(expected_exception=InvalidRequest):
        add_reply_to_email_address_for_service(
            service_id=service.id, email_address='first@address.com', is_default=False
        )


def test_add_reply_to_email_address_ensure_there_is_not_more_than_one_default(sample_service):
    service = sample_service()
    create_reply_to_email(service=service, email_address='first@email.com', is_default=True)
    create_reply_to_email(service=service, email_address='second@email.com', is_default=True)
    with pytest.raises(Exception):
        add_reply_to_email_address_for_service(
            service_id=service.id, email_address='third_email@address.com', is_default=False
        )


def test_update_reply_to_email_address(sample_service):
    service = sample_service(email_address=None)
    first_reply_to = create_reply_to_email(service=service, email_address='first@address.com')
    update_reply_to_email_address(
        service_id=service.id,
        reply_to_id=first_reply_to.id,
        email_address='change_address@email.com',
        is_default=True,
    )
    updated_reply_to = ServiceEmailReplyTo.query.get(first_reply_to.id)

    assert updated_reply_to.email_address == 'change_address@email.com'
    assert updated_reply_to.updated_at
    assert updated_reply_to.is_default


def test_update_reply_to_email_address_set_updated_to_default(
    notify_db_session,
    sample_service,
):
    service = sample_service(email_address=None)
    create_reply_to_email(service=service, email_address='first@address.com')
    second_reply_to = create_reply_to_email(service=service, email_address='second@address.com', is_default=False)

    update_reply_to_email_address(
        service_id=service.id,
        reply_to_id=second_reply_to.id,
        email_address='change_address@email.com',
        is_default=True,
    )

    stmt = select(ServiceEmailReplyTo).where(ServiceEmailReplyTo.service_id == service.id)
    results = notify_db_session.session.scalars(stmt).all()
    assert len(results) == 2
    for x in results:
        if x.email_address == 'change_address@email.com':
            assert x.is_default
        elif x.email_address == 'first@address.com':
            assert not x.is_default
        else:
            assert False


def test_update_reply_to_email_address_raises_exception_if_single_reply_to_and_setting_default_to_false(sample_service):
    email_address = f'{str(uuid.uuid4())}@example.com'
    different_email_address = f'{str(uuid.uuid4())}2@example.com'
    service = sample_service(email_address=None)

    first_reply_to = create_reply_to_email(service=service, email_address=email_address)
    with pytest.raises(expected_exception=InvalidRequest):
        update_reply_to_email_address(
            service_id=service.id,
            reply_to_id=first_reply_to.id,
            email_address=different_email_address,
            is_default=False,
        )


def test_dao_get_reply_to_by_id(sample_service):
    service = sample_service()
    reply_to = create_reply_to_email(service=service, email_address=f'{str(uuid.uuid4())}@example.com')
    result = dao_get_reply_to_by_id(service_id=service.id, reply_to_id=reply_to.id)
    assert result == reply_to


def test_dao_get_reply_to_by_id_raises_sqlalchemy_error_when_reply_to_does_not_exist(sample_service):
    with pytest.raises(SQLAlchemyError):
        dao_get_reply_to_by_id(service_id=sample_service().id, reply_to_id=uuid.uuid4())


def test_dao_get_reply_to_by_id_raises_sqlalchemy_error_when_reply_to_is_archived(sample_service):
    service = sample_service()
    create_reply_to_email(service=service, email_address=f'{str(uuid.uuid4())}@example.com')
    archived_reply_to = create_reply_to_email(
        service=service, email_address='email_two@address.com', is_default=False, archived=True
    )

    with pytest.raises(SQLAlchemyError):
        dao_get_reply_to_by_id(service_id=service.id, reply_to_id=archived_reply_to.id)


def test_dao_get_reply_to_by_id_raises_sqlalchemy_error_when_service_does_not_exist(sample_service):
    reply_to = create_reply_to_email(service=sample_service(), email_address=f'{str(uuid.uuid4())}@example.com')
    with pytest.raises(SQLAlchemyError):
        dao_get_reply_to_by_id(service_id=uuid.uuid4(), reply_to_id=reply_to.id)


def test_archive_reply_to_email_address(sample_service):
    service = sample_service()
    create_reply_to_email(service=service, email_address=f'{str(uuid.uuid4())}@example.com')
    second_reply_to = create_reply_to_email(
        service=service, email_address=f'{str(uuid.uuid4())}@example.com', is_default=False
    )

    archive_reply_to_email_address(service.id, second_reply_to.id)

    assert second_reply_to.archived is True
    assert second_reply_to.updated_at is not None


def test_archive_reply_to_email_address_does_not_archive_a_reply_to_for_a_different_service(sample_service):
    service = sample_service()
    different_service = sample_service()

    reply_to = create_reply_to_email(
        service=different_service,
        email_address=f'{str(uuid.uuid4())}@example.com',
        is_default=False,
    )

    with pytest.raises(SQLAlchemyError):
        archive_reply_to_email_address(service.id, reply_to.id)

    assert not reply_to.archived


def test_archive_reply_to_email_address_raises_an_error_if_attempting_to_archive_a_default(sample_service):
    service = sample_service()

    email_to_duplicate = f'{str(uuid.uuid4())}@example.com'
    create_reply_to_email(service=service, email_address=email_to_duplicate, is_default=False)
    default_reply_to = create_reply_to_email(service=service, email_address=email_to_duplicate)

    with pytest.raises(ArchiveValidationError) as e:
        archive_reply_to_email_address(service.id, default_reply_to.id)

    assert 'You cannot delete a default email reply to address' in str(e.value)
    assert not default_reply_to.archived
