"""
A bunch of these tests use the notify_db_session fixture but don't reference it.  It
seems that using the fixture has side-effects that ensure a test database is used.
Without passing notify_db_session, tests fail.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DataError, SQLAlchemyError

from app.dao.service_sms_sender_dao import (
    archive_sms_sender,
    dao_add_sms_sender_for_service,
    dao_get_service_sms_sender_by_id,
    dao_get_service_sms_sender_by_service_id_and_number,
    dao_get_sms_senders_by_service_id,
    dao_update_service_sms_sender,
    _validate_rate_limit,
)
from app.exceptions import ArchiveValidationError
from app.models import InboundNumber, ServiceSmsSender
from app.service.exceptions import (
    SmsSenderDefaultValidationException,
    SmsSenderInboundNumberIntegrityException,
    SmsSenderProviderValidationException,
    SmsSenderRateLimitIntegrityException,
)
from tests.app.db import create_service_sms_sender


def test_dao_get_service_sms_sender_by_id(sample_provider, sample_service):
    provider = sample_provider()
    service = sample_service()
    second_sender = dao_add_sms_sender_for_service(
        service_id=service.id,
        sms_sender='second',
        is_default=False,
        inbound_number_id=None,
        provider_id=provider.id,
        description='test',
    )

    service_sms_sender = dao_get_service_sms_sender_by_id(service_id=service.id, service_sms_sender_id=second_sender.id)

    assert service_sms_sender.sms_sender == 'second'
    assert not service_sms_sender.is_default
    assert isinstance(service_sms_sender.sms_sender_specifics, dict) and not service_sms_sender.sms_sender_specifics, (
        'This should be an empty dictionary by default.'
    )


def test_dao_get_service_sms_sender_by_id_with_sender_specifics(sample_provider, sample_service):
    sender_specifics = {
        'provider': 'Twilio',
        'misc': 'This is some text.',
        'some_value': 42,
    }
    provider = sample_provider()

    service = sample_service()
    second_sender = dao_add_sms_sender_for_service(
        service_id=service.id,
        sms_sender='second',
        is_default=False,
        inbound_number_id=None,
        sms_sender_specifics=sender_specifics,
        provider_id=provider.id,
        description='test',
    )

    service_sms_sender = dao_get_service_sms_sender_by_id(service_id=service.id, service_sms_sender_id=second_sender.id)

    assert service_sms_sender.sms_sender == 'second'
    assert not service_sms_sender.is_default
    assert service_sms_sender.sms_sender_specifics == sender_specifics


def test_dao_get_service_sms_sender_by_id_raise_exception_when_not_found(sample_service):
    service = sample_service()
    with pytest.raises(expected_exception=SQLAlchemyError):
        dao_get_service_sms_sender_by_id(service_id=service.id, service_sms_sender_id=uuid.uuid4())


def test_dao_get_service_sms_senders_id_raises_exception_with_archived_sms_sender(sample_service):
    service = sample_service()
    archived_sms_sender = create_service_sms_sender(
        service=service, sms_sender='second', is_default=False, archived=True
    )
    with pytest.raises(expected_exception=SQLAlchemyError):
        dao_get_service_sms_sender_by_id(service_id=service.id, service_sms_sender_id=archived_sms_sender.id)


def test_dao_get_sms_senders_by_service_id(sample_provider, sample_service):
    provider = sample_provider()
    service = sample_service()

    second_sender = dao_add_sms_sender_for_service(
        service_id=service.id,
        sms_sender='second',
        is_default=False,
        inbound_number_id=None,
        provider_id=provider.id,
        description='test',
    )

    sms_senders = dao_get_sms_senders_by_service_id(service_id=service.id)

    assert len(sms_senders) == 2

    for sms_sender in sms_senders:
        if sms_sender.is_default:
            assert sms_sender.sms_sender == 'testing'
        else:
            assert sms_sender == second_sender


def test_dao_get_sms_senders_by_service_id_does_not_return_archived_senders(
    sample_service,
):
    service = sample_service()
    archived_sms_sender = create_service_sms_sender(
        service=service, sms_sender='second', is_default=False, archived=True
    )

    sms_senders = dao_get_sms_senders_by_service_id(service_id=service.id)

    assert len(sms_senders) == 1
    assert archived_sms_sender not in sms_senders


class TestDaoAddSmsSenderForService:
    def test_dao_add_sms_sender_for_service(self, notify_db_session, sample_provider, sample_service) -> None:
        provider = sample_provider()
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        service_sms_senders = notify_db_session.session.scalars(stmt).all()

        assert len(service_sms_senders) == 1

        # service_cleanup will handle Teardown
        new_sms_sender = dao_add_sms_sender_for_service(
            service_id=service.id,
            sms_sender='new_sms',
            is_default=False,
            inbound_number_id=None,
            provider_id=provider.id,
            description='test',
        )

        service_sms_senders_after_updates = notify_db_session.session.scalars(stmt).all()

        assert len(service_sms_senders_after_updates) == 2

        assert new_sms_sender in service_sms_senders_after_updates

    def test_dao_add_sms_sender_256_char(self, notify_db_session, sample_provider, sample_service) -> None:
        provider = sample_provider()
        service = sample_service()

        # service_cleanup will handle Teardown
        new_sms_sender = dao_add_sms_sender_for_service(
            service_id=service.id,
            sms_sender='1' * 256,
            is_default=False,
            inbound_number_id=None,
            provider_id=provider.id,
            description='test',
        )

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        service_sms_senders_after_updates = notify_db_session.session.scalars(stmt).all()

        assert new_sms_sender in service_sms_senders_after_updates

    def test_dao_switches_default(self, notify_db_session, sample_provider, sample_service) -> None:
        provider = sample_provider()
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        existing_sms_sender = notify_db_session.session.scalars(stmt).one()

        # service_cleanup will handle Teardown
        new_sms_sender = dao_add_sms_sender_for_service(
            service_id=service.id,
            sms_sender='new_sms',
            is_default=True,
            inbound_number_id=None,
            provider_id=provider.id,
            description='test',
        )

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.id == existing_sms_sender.id)
        existing_sms_sender_after_updates = notify_db_session.session.scalars(stmt).one()

        assert not existing_sms_sender_after_updates.is_default

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.id == new_sms_sender.id)
        new_sms_sender_after_updates = notify_db_session.session.scalars(stmt).one()

        assert new_sms_sender_after_updates.is_default

    def test_dao_add_sms_sender_raises_exception_if_sms_sender_too_long(
        self,
        notify_db_session,
        sample_provider,
        sample_service,
    ) -> None:
        provider = sample_provider()
        service = sample_service()

        with pytest.raises(DataError):
            dao_add_sms_sender_for_service(
                service_id=service.id,
                sms_sender='1' * 257,
                is_default=False,
                inbound_number_id=None,
                provider_id=provider.id,
                description='test',
            )

    @pytest.mark.parametrize('rate_limit, rate_limit_interval', ([1, None], [None, 1]))
    def test_raises_exception_if_only_one_of_rate_limit_value_and_interval_provided(
        self,
        notify_db_session,
        sample_service,
        rate_limit,
        rate_limit_interval,
    ) -> None:
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        service_sms_senders = notify_db_session.session.scalars(stmt).all()

        assert len(service_sms_senders) == 1

        with pytest.raises(SmsSenderRateLimitIntegrityException) as e:
            dao_add_sms_sender_for_service(
                service_id=service.id,
                sms_sender='new_sms',
                is_default=False,
                inbound_number_id=None,
                rate_limit=rate_limit,
                rate_limit_interval=rate_limit_interval,
                provider_id=None,
                description='test',
            )

        assert 'Provide both rate_limit and rate_limit_interval' in str(e.value)

    def test_raises_exception_if_adding_number_to_use_already_allocated_inbound_number(
        self,
        notify_db_session,
        sample_service,
        sample_service_with_inbound_number,
    ) -> None:
        service_with_inbound_number = sample_service_with_inbound_number()

        stmt = select(InboundNumber).where(InboundNumber.service_id == service_with_inbound_number.id)
        inbound_number = notify_db_session.session.scalars(stmt).one()

        new_service = sample_service()

        with pytest.raises(SmsSenderInboundNumberIntegrityException) as e:
            dao_add_sms_sender_for_service(
                service_id=new_service.id,
                sms_sender='new-number',
                is_default=False,
                inbound_number_id=inbound_number.id,
                provider_id=None,
                description='test',
            )

        expected_msg = f'Inbound number: {inbound_number.id} is not available'
        assert expected_msg in str(e.value)

    def test_raises_exception_if_adding_number_different_to_inbound_number(
        self,
        sample_service,
        sample_inbound_number,
    ):
        service = sample_service()
        inbound_number = sample_inbound_number()
        wrong_number = sample_inbound_number()

        with pytest.raises(SmsSenderInboundNumberIntegrityException):
            dao_add_sms_sender_for_service(
                service_id=service.id,
                sms_sender=wrong_number.number,
                is_default=False,
                inbound_number_id=inbound_number.id,
                provider_id=None,
                description='test',
            )

    def test_raises_exception_for_zero_rate_limit(self, notify_db_session, sample_service):
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        service_sms_senders = notify_db_session.session.scalars(stmt).all()

        assert len(service_sms_senders) == 1

        with pytest.raises(SmsSenderRateLimitIntegrityException) as e:
            dao_add_sms_sender_for_service(
                service_id=service.id,
                sms_sender='new_sms',
                is_default=False,
                inbound_number_id=None,
                rate_limit=0,
                rate_limit_interval=1,
                provider_id=None,
                description='test',
            )

        assert 'rate_limit cannot be less than 1.' in str(e.value)

    def test_raises_exception_for_zero_rate_limit_interval(
        self,
        notify_db_session,
        sample_service,
    ):
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        service_sms_senders = notify_db_session.session.scalars(stmt).all()

        assert len(service_sms_senders) == 1

        with pytest.raises(SmsSenderRateLimitIntegrityException) as e:
            dao_add_sms_sender_for_service(
                service_id=service.id,
                sms_sender='new_sms',
                is_default=False,
                inbound_number_id=None,
                rate_limit=1,
                rate_limit_interval=0,
                provider_id=None,
                description='test',
            )

        assert 'rate_limit_interval cannot be less than 1.' in str(e.value)

    def test_raises_exception_attempting_to_add_invalid_provider(self, sample_service) -> None:
        service = sample_service()

        with pytest.raises(SmsSenderProviderValidationException) as e:
            dao_add_sms_sender_for_service(
                service_id=service.id,
                sms_sender='new_sms',
                is_default=False,
                inbound_number_id=None,
                provider_id=uuid.uuid4(),
                description='test',
            )

        assert 'No provider details found for id' in str(e.value)


class TestDaoUpdateServiceUpdateSmsSender:
    def test_dao_update_service_sms_sender(
        self,
        notify_db_session,
        sample_service,
        sample_inbound_number,
    ):
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        existing_sms_sender = notify_db_session.session.scalars(stmt).one()

        sender_specifics = {'data': 'This is something specific.', 'some_int': 42}
        inbound_number = sample_inbound_number()

        dao_update_service_sms_sender(
            service_id=service.id,
            service_sms_sender_id=existing_sms_sender.id,
            sms_sender='updated',
            inbound_number_id=inbound_number.id,
            sms_sender_specifics=sender_specifics,
        )

        existing_sms_sender_after_updates = notify_db_session.session.scalars(stmt).one()

        assert existing_sms_sender_after_updates.is_default
        assert existing_sms_sender_after_updates.sms_sender == 'updated'
        assert existing_sms_sender_after_updates.inbound_number_id == inbound_number.id
        assert existing_sms_sender_after_updates.sms_sender_specifics == sender_specifics

    def test_switches_default(self, notify_db_session, sample_provider, sample_service) -> None:
        provider = sample_provider()
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        existing_sms_sender = notify_db_session.session.scalars(stmt).one()

        new_sms_sender = dao_add_sms_sender_for_service(
            service_id=service.id,
            sms_sender='new_sms',
            is_default=False,
            inbound_number_id=None,
            provider_id=provider.id,
            description='test',
        )

        dao_update_service_sms_sender(service_id=service.id, service_sms_sender_id=new_sms_sender.id, is_default=True)

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.id == existing_sms_sender.id)
        existing_sms_sender_after_updates = notify_db_session.session.scalars(stmt).one()

        assert not existing_sms_sender_after_updates.is_default

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.id == new_sms_sender.id)
        new_sms_sender_after_updates = notify_db_session.session.scalars(stmt).one()

        assert new_sms_sender_after_updates.is_default

    @pytest.mark.parametrize('rate_limit, rate_limit_interval', ([1, None], [None, 1]))
    def test_raises_exception_if_only_one_of_rate_limit_value_and_interval_provided(
        self, notify_db_session, sample_service, rate_limit, rate_limit_interval
    ):
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        existing_sms_sender = notify_db_session.session.scalars(stmt).one()

        with pytest.raises(SmsSenderRateLimitIntegrityException) as e:
            dao_update_service_sms_sender(
                service_id=service.id,
                service_sms_sender_id=existing_sms_sender.id,
                rate_limit=rate_limit,
                rate_limit_interval=rate_limit_interval,
            )

        assert 'Cannot update sender to have only one of rate limit value and interval.' in str(e.value)

    def test_raises_exception_for_zero_rate_limit(self, notify_db_session, sample_service):
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        existing_sms_sender = notify_db_session.session.scalars(stmt).one()

        with pytest.raises(Exception) as e:
            dao_update_service_sms_sender(
                service_id=service.id, service_sms_sender_id=existing_sms_sender.id, rate_limit=0, rate_limit_interval=1
            )

        assert 'rate_limit cannot be less than 1.' in str(e.value)

    def test_raises_exception_for_zero_rate_limit_interval(self, notify_db_session, sample_service):
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        existing_sms_sender = notify_db_session.session.scalars(stmt).one()

        with pytest.raises(Exception) as e:
            dao_update_service_sms_sender(
                service_id=service.id, service_sms_sender_id=existing_sms_sender.id, rate_limit=1, rate_limit_interval=0
            )

        assert 'rate_limit_interval cannot be less than 1.' in str(e.value)

    def test_raises_exception_if_update_would_result_in_no_default_sms_sender(self, notify_db_session, sample_service):
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        existing_sms_sender = notify_db_session.session.scalars(stmt).one()

        with pytest.raises(SmsSenderDefaultValidationException) as e:
            dao_update_service_sms_sender(
                service_id=service.id,
                service_sms_sender_id=existing_sms_sender.id,
                is_default=False,
                sms_sender='updated',
            )

        assert 'You must have at least one SMS sender as the default.' in str(e.value)

    def test_raises_exception_if_updating_number_with_inbound_number_already_set(
        self,
        notify_db_session,
        sample_inbound_number,
        sample_service,
    ):
        service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        existing_sms_sender = notify_db_session.session.scalars(stmt).one()

        inbound_number = sample_inbound_number()
        dao_update_service_sms_sender(
            service_id=service.id, service_sms_sender_id=existing_sms_sender.id, inbound_number_id=inbound_number.id
        )

        with pytest.raises(SmsSenderInboundNumberIntegrityException) as e:
            dao_update_service_sms_sender(
                service_id=service.id, service_sms_sender_id=existing_sms_sender.id, sms_sender='new-number'
            )

        expected_msg = 'You cannot update the number for this SMS sender because it has an associated Inbound Number.'
        assert expected_msg in str(e.value)

    def test_raises_exception_if_updating_number_to_use_already_allocated_inbound_number(
        self,
        notify_db_session,
        sample_service,
        sample_service_with_inbound_number,
    ):
        service_with_inbound_number = sample_service_with_inbound_number()

        stmt = select(InboundNumber).where(InboundNumber.service_id == service_with_inbound_number.id)
        inbound_number = notify_db_session.session.scalars(stmt).one()

        new_service = sample_service()

        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service_with_inbound_number.id)
        existing_sms_sender = notify_db_session.session.scalars(stmt).one()

        with pytest.raises(SmsSenderInboundNumberIntegrityException) as e:
            dao_update_service_sms_sender(
                service_id=new_service.id,
                service_sms_sender_id=existing_sms_sender.id,
                inbound_number_id=inbound_number.id,
            )

        expected_msg = f'Inbound number: {inbound_number.id} is not available.'
        assert expected_msg in str(e.value)


def test_archive_sms_sender(sample_provider, sample_service) -> None:
    provider = sample_provider()
    service = sample_service()
    second_sms_sender = dao_add_sms_sender_for_service(
        service_id=service.id,
        sms_sender='second',
        is_default=False,
        provider_id=provider.id,
        description='test',
    )

    archive_sms_sender(service_id=service.id, sms_sender_id=second_sms_sender.id)

    assert second_sms_sender.archived
    assert second_sms_sender.updated_at is not None


def test_archive_sms_sender_does_not_archive_a_sender_for_a_different_service(
    sample_provider,
    sample_service,
) -> None:
    provider = sample_provider()
    service = sample_service(service_name=f'{str(uuid.uuid4())}First service')
    sms_sender = dao_add_sms_sender_for_service(
        service_id=sample_service().id,
        sms_sender='second',
        is_default=False,
        provider_id=provider.id,
        description='test',
    )

    with pytest.raises(SQLAlchemyError):
        archive_sms_sender(service.id, sms_sender.id)

    assert not sms_sender.archived


def test_archive_sms_sender_raises_an_error_if_attempting_to_archive_a_default(sample_service):
    service = sample_service()
    sms_sender = service.service_sms_senders[0]

    with pytest.raises(ArchiveValidationError) as e:
        archive_sms_sender(service_id=service.id, sms_sender_id=sms_sender.id)

    assert 'You cannot delete a default sms sender.' in str(e.value)


@pytest.mark.parametrize('is_default', [True, False])
def test_archive_sms_sender_raises_an_error_if_attempting_to_archive_an_inbound_number(
    notify_db_session,
    sample_provider,
    sample_service_with_inbound_number,
    is_default,
) -> None:
    provider = sample_provider()
    service = sample_service_with_inbound_number()
    dao_add_sms_sender_for_service(service.id, 'second', is_default=True, provider_id=provider.id, description='test')

    inbound_number = next(x for x in service.service_sms_senders if x.inbound_number_id)

    # regardless of whether inbound number is default or not, can't delete it
    dao_update_service_sms_sender(service.id, inbound_number.id, is_default=is_default)

    with pytest.raises(ArchiveValidationError) as e:
        archive_sms_sender(service_id=service.id, sms_sender_id=inbound_number.id)

    assert 'You cannot delete an inbound number.' in str(e.value)
    assert not inbound_number.archived


class TestGetSmsSenderByServiceIdAndNumber:
    def test_returns_none_if_no_matching_service_id(self, notify_db_session, sample_service):
        service_with_sms_sender = sample_service()
        sms_sender = ServiceSmsSender(sms_sender='+15551234567', service_id=service_with_sms_sender.id)
        notify_db_session.session.add(sms_sender)
        notify_db_session.session.commit()

        service_without_sms_sender = sample_service()
        found_sms_sender = dao_get_service_sms_sender_by_service_id_and_number(
            service_id=service_without_sms_sender.id, number='+15551234567'
        )

        assert found_sms_sender is None

    def test_returns_none_if_no_matching_number(self, notify_db_session, sample_service):
        service = sample_service()
        sms_sender = ServiceSmsSender(sms_sender='+15551234567', service_id=service.id)
        notify_db_session.session.add(sms_sender)
        notify_db_session.session.commit()

        found_sms_sender = dao_get_service_sms_sender_by_service_id_and_number(
            service_id=service.id, number='+15557654321'
        )

        assert found_sms_sender is None

    def test_returns_sms_sender_if_matching_service_and_number(self, notify_db_session, sample_service):
        service = sample_service()
        sms_sender = ServiceSmsSender(sms_sender='+15551234567', service_id=service.id)
        notify_db_session.session.add(sms_sender)
        notify_db_session.session.commit()

        found_sms_sender = dao_get_service_sms_sender_by_service_id_and_number(
            service_id=service.id, number='+15551234567'
        )

        assert found_sms_sender is sms_sender


@pytest.mark.parametrize(
    'rate_limit, rate_limit_interval, raises_exception',
    (
        [1, 1, False],
        [1, None, True],
        [None, 1, True],
        [None, None, False],
        [-1, 1, True],
        [1, -1, True],
    ),
)
def test_validate_rate_limit(rate_limit, rate_limit_interval, raises_exception) -> None:
    """Test that rate_limit and rate_limit_interval are validated correctly, raising an exception when necessary."""
    sms_sender = ServiceSmsSender(service_id=uuid.uuid4())

    if raises_exception:
        with pytest.raises(SmsSenderRateLimitIntegrityException):
            _validate_rate_limit(sms_sender, rate_limit, rate_limit_interval)
    else:
        assert _validate_rate_limit(sms_sender, rate_limit, rate_limit_interval) is None
