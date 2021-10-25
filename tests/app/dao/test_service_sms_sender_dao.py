import uuid

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.dao.service_sms_sender_dao import (
    archive_sms_sender,
    dao_add_sms_sender_for_service,
    dao_update_service_sms_sender,
    dao_get_service_sms_sender_by_id,
    dao_get_sms_senders_by_service_id,
    dao_get_sms_sender_by_service_id_and_number
)
from app.service.exceptions import SmsSenderDefaultValidationException, SmsSenderInboundNumberIntegrityException, \
    SmsSenderRateLimitIntegrityException
from app.exceptions import ArchiveValidationError
from app.models import ServiceSmsSender, InboundNumber
from tests.app.db import (
    create_inbound_number,
    create_service,
    create_service_sms_sender,
    create_service_with_inbound_number)


def test_dao_get_service_sms_sender_by_id(notify_db_session):
    service = create_service()
    second_sender = dao_add_sms_sender_for_service(service_id=service.id,
                                                   sms_sender='second',
                                                   is_default=False,
                                                   inbound_number_id=None)
    result = dao_get_service_sms_sender_by_id(service_id=service.id,
                                              service_sms_sender_id=second_sender.id)
    assert result.sms_sender == "second"
    assert not result.is_default


def test_dao_get_service_sms_sender_by_id_raise_exception_when_not_found(notify_db_session):
    service = create_service()
    with pytest.raises(expected_exception=SQLAlchemyError):
        dao_get_service_sms_sender_by_id(service_id=service.id,
                                         service_sms_sender_id=uuid.uuid4())


def test_dao_get_service_sms_senders_id_raises_exception_with_archived_sms_sender(notify_db_session):
    service = create_service()
    archived_sms_sender = create_service_sms_sender(
        service=service,
        sms_sender="second",
        is_default=False,
        archived=True)
    with pytest.raises(expected_exception=SQLAlchemyError):
        dao_get_service_sms_sender_by_id(service_id=service.id,
                                         service_sms_sender_id=archived_sms_sender.id)


def test_dao_get_sms_senders_by_service_id(notify_db_session):
    service = create_service()
    second_sender = dao_add_sms_sender_for_service(service_id=service.id,
                                                   sms_sender='second',
                                                   is_default=False,
                                                   inbound_number_id=None)
    results = dao_get_sms_senders_by_service_id(service_id=service.id)
    assert len(results) == 2
    for x in results:
        if x.is_default:
            assert x.sms_sender == 'testing'
        else:
            assert x == second_sender


def test_dao_get_sms_senders_by_service_id_does_not_return_archived_senders(notify_db_session):
    service = create_service()
    archived_sms_sender = create_service_sms_sender(
        service=service,
        sms_sender="second",
        is_default=False,
        archived=True)
    results = dao_get_sms_senders_by_service_id(service_id=service.id)

    assert len(results) == 1
    assert archived_sms_sender not in results


class TestDaoAddSmsSenderForService:

    def test_dao_add_sms_sender_for_service(self, notify_db_session):
        service = create_service()

        service_sms_senders = ServiceSmsSender.query.filter_by(service_id=service.id).all()
        assert len(service_sms_senders) == 1

        new_sms_sender = dao_add_sms_sender_for_service(
            service_id=service.id,
            sms_sender='new_sms',
            is_default=False,
            inbound_number_id=None
        )

        service_sms_senders_after_updates = ServiceSmsSender.query.filter_by(service_id=service.id).all()
        assert len(service_sms_senders_after_updates) == 2

        assert new_sms_sender in service_sms_senders_after_updates

    def test_dao_switches_default(self, notify_db_session):
        service = create_service()
        existing_sms_sender = ServiceSmsSender.query.filter_by(service_id=service.id).one()

        new_sms_sender = dao_add_sms_sender_for_service(
            service_id=service.id,
            sms_sender='new_sms',
            is_default=True,
            inbound_number_id=None
        )

        existing_sms_sender_after_updates = ServiceSmsSender.query.filter_by(id=existing_sms_sender.id).one()
        assert not existing_sms_sender_after_updates.is_default

        new_sms_sender_after_updates = ServiceSmsSender.query.filter_by(id=new_sms_sender.id).one()
        assert new_sms_sender_after_updates.is_default

    @pytest.mark.parametrize('rate_limit, rate_limit_interval', ([1, None], [None, 1]))
    def test_raises_exception_if_only_one_of_rate_limit_value_and_interval_provided(self, notify_db_session,
                                                                                    rate_limit, rate_limit_interval):
        service = create_service()

        service_sms_senders = ServiceSmsSender.query.filter_by(service_id=service.id).all()
        assert len(service_sms_senders) == 1

        with pytest.raises(SmsSenderRateLimitIntegrityException) as e:
            dao_add_sms_sender_for_service(
                service_id=service.id,
                sms_sender='new_sms',
                is_default=False,
                inbound_number_id=None,
                rate_limit=rate_limit,
                rate_limit_interval=rate_limit_interval
            )

        assert 'Must provide both rate limit value and interval' in str(e.value)

    def test_raises_exception_if_adding_number_to_use_already_allocated_inbound_number(self, notify_db_session):
        service_with_inbound_number = create_service_with_inbound_number()
        inbound_number = InboundNumber.query.filter_by(service_id=service_with_inbound_number.id).one()

        new_service = create_service(service_name='new service')

        with pytest.raises(SmsSenderInboundNumberIntegrityException) as e:
            dao_add_sms_sender_for_service(
                service_id=new_service.id,
                sms_sender='new-number',
                is_default=False,
                inbound_number_id=inbound_number.id
            )

        expected_msg = f'Inbound number: {inbound_number.id} is not available'
        assert expected_msg in str(e.value)

    def test_raises_exception_if_adding_number_different_to_inbound_number(self, notify_db_session):
        service = create_service()
        inbound_number = create_inbound_number(number='+15551234567')

        with pytest.raises(SmsSenderInboundNumberIntegrityException):
            dao_add_sms_sender_for_service(
                service_id=service.id,
                sms_sender='+15557654321',
                is_default=False,
                inbound_number_id=inbound_number.id
            )

    def test_raises_exception_for_zero_rate_limit(self, notify_db_session):
        service = create_service()

        service_sms_senders = ServiceSmsSender.query.filter_by(service_id=service.id).all()
        assert len(service_sms_senders) == 1

        with pytest.raises(SmsSenderRateLimitIntegrityException) as e:
            dao_add_sms_sender_for_service(
                service_id=service.id,
                sms_sender='new_sms',
                is_default=False,
                inbound_number_id=None,
                rate_limit=0,
                rate_limit_interval=1
            )

        assert "Rate limit value cannot be below 1" in str(e.value)

    def test_raises_exception_for_zero_rate_limit_interval(self, notify_db_session):
        service = create_service()

        service_sms_senders = ServiceSmsSender.query.filter_by(service_id=service.id).all()
        assert len(service_sms_senders) == 1

        with pytest.raises(SmsSenderRateLimitIntegrityException) as e:
            dao_add_sms_sender_for_service(
                service_id=service.id,
                sms_sender='new_sms',
                is_default=False,
                inbound_number_id=None,
                rate_limit=1,
                rate_limit_interval=0
            )

        assert "Rate limit interval cannot be below 1" in str(e.value)


class TestDaoUpdateServiceUpdateSmsSender:

    def test_dao_update_service_sms_sender(self, notify_db_session):
        service = create_service()
        existing_sms_sender = ServiceSmsSender.query.filter_by(service_id=service.id).one()

        inbound_number = create_inbound_number('+5551234567')
        dao_update_service_sms_sender(
            service_id=service.id,
            service_sms_sender_id=existing_sms_sender.id,
            sms_sender='updated',
            inbound_number_id=inbound_number.id
        )

        existing_sms_sender_after_updates = ServiceSmsSender.query.filter_by(service_id=service.id).one()
        assert existing_sms_sender_after_updates.is_default
        assert existing_sms_sender_after_updates.sms_sender == 'updated'
        assert existing_sms_sender_after_updates.inbound_number_id == inbound_number.id

    def test_switches_default(self, notify_db_session):
        service = create_service()
        existing_sms_sender = ServiceSmsSender.query.filter_by(service_id=service.id).one()

        new_sms_sender = dao_add_sms_sender_for_service(
            service_id=service.id,
            sms_sender='new_sms',
            is_default=False,
            inbound_number_id=None
        )

        dao_update_service_sms_sender(
            service_id=service.id,
            service_sms_sender_id=new_sms_sender.id,
            is_default=True
        )

        existing_sms_sender_after_updates = ServiceSmsSender.query.filter_by(id=existing_sms_sender.id).one()
        assert not existing_sms_sender_after_updates.is_default

        new_sms_sender_after_updates = ServiceSmsSender.query.filter_by(id=new_sms_sender.id).one()
        assert new_sms_sender_after_updates.is_default

    @pytest.mark.parametrize('rate_limit, rate_limit_interval', ([1, None], [None, 1]))
    def test_raises_exception_if_only_one_of_rate_limit_value_and_interval_provided(self, notify_db_session,
                                                                                    rate_limit, rate_limit_interval):
        service = create_service()
        existing_sms_sender = ServiceSmsSender.query.filter_by(service_id=service.id).one()

        with pytest.raises(SmsSenderRateLimitIntegrityException) as e:
            dao_update_service_sms_sender(
                service_id=service.id,
                service_sms_sender_id=existing_sms_sender.id,
                rate_limit=rate_limit,
                rate_limit_interval=rate_limit_interval
            )

        assert 'Cannot update sender to have only one of rate limit value and interval' in str(e.value)

    def test_raises_exception_for_zero_rate_limit(self, notify_db_session):
        service = create_service()
        existing_sms_sender = ServiceSmsSender.query.filter_by(service_id=service.id).one()

        with pytest.raises(Exception) as e:
            dao_update_service_sms_sender(
                service_id=service.id,
                service_sms_sender_id=existing_sms_sender.id,
                rate_limit=0,
                rate_limit_interval=1
            )

        assert 'Rate limit value cannot be below 1' in str(e.value)

    def test_raises_exception_for_zero_rate_limit_interval(self, notify_db_session):
        service = create_service()
        existing_sms_sender = ServiceSmsSender.query.filter_by(service_id=service.id).one()

        with pytest.raises(Exception) as e:
            dao_update_service_sms_sender(
                service_id=service.id,
                service_sms_sender_id=existing_sms_sender.id,
                rate_limit=1,
                rate_limit_interval=0
            )

        assert 'Rate limit interval cannot be below 1' in str(e.value)

    def test_raises_exception_if_update_would_result_in_no_default_sms_sender(self, notify_db_session):
        service = create_service()
        existing_sms_sender = ServiceSmsSender.query.filter_by(service_id=service.id).one()

        with pytest.raises(SmsSenderDefaultValidationException) as e:
            dao_update_service_sms_sender(
                service_id=service.id,
                service_sms_sender_id=existing_sms_sender.id,
                is_default=False,
                sms_sender="updated"
            )

        assert 'You must have at least one SMS sender as the default' in str(e.value)

    def test_raises_exception_if_updating_number_with_inbound_number_already_set(self, notify_db_session):
        service = create_service()
        existing_sms_sender = ServiceSmsSender.query.filter_by(service_id=service.id).one()

        inbound_number = create_inbound_number('+5551234567')
        dao_update_service_sms_sender(
            service_id=service.id,
            service_sms_sender_id=existing_sms_sender.id,
            inbound_number_id=inbound_number.id
        )

        with pytest.raises(SmsSenderInboundNumberIntegrityException) as e:
            dao_update_service_sms_sender(
                service_id=service.id,
                service_sms_sender_id=existing_sms_sender.id,
                sms_sender='new-number'
            )

        expected_msg = 'You cannot update the number for this SMS sender as it has an associated Inbound Number'
        assert expected_msg in str(e.value)

    def test_raises_exception_if_updating_number_to_use_already_allocated_inbound_number(self, notify_db_session):
        service_with_inbound_number = create_service_with_inbound_number()
        inbound_number = InboundNumber.query.filter_by(service_id=service_with_inbound_number.id).one()

        new_service = create_service(service_name='new service')
        existing_sms_sender = ServiceSmsSender.query.filter_by(service_id=service_with_inbound_number.id).one()

        with pytest.raises(SmsSenderInboundNumberIntegrityException) as e:
            dao_update_service_sms_sender(
                service_id=new_service.id,
                service_sms_sender_id=existing_sms_sender.id,
                inbound_number_id=inbound_number.id
            )

        expected_msg = f'Inbound number: {inbound_number.id} is not available'
        assert expected_msg in str(e.value)


def test_archive_sms_sender(notify_db_session):
    service = create_service()
    second_sms_sender = dao_add_sms_sender_for_service(service_id=service.id,
                                                       sms_sender='second',
                                                       is_default=False)

    archive_sms_sender(service_id=service.id, sms_sender_id=second_sms_sender.id)

    assert second_sms_sender.archived is True
    assert second_sms_sender.updated_at is not None


def test_archive_sms_sender_does_not_archive_a_sender_for_a_different_service(sample_service):
    service = create_service(service_name="First service")
    sms_sender = dao_add_sms_sender_for_service(service_id=sample_service.id,
                                                sms_sender='second',
                                                is_default=False)

    with pytest.raises(SQLAlchemyError):
        archive_sms_sender(service.id, sms_sender.id)

    assert not sms_sender.archived


def test_archive_sms_sender_raises_an_error_if_attempting_to_archive_a_default(notify_db_session):
    service = create_service()
    sms_sender = service.service_sms_senders[0]

    with pytest.raises(ArchiveValidationError) as e:
        archive_sms_sender(service_id=service.id, sms_sender_id=sms_sender.id)

    assert 'You cannot delete a default sms sender' in str(e.value)


@pytest.mark.parametrize('is_default', [True, False])
def test_archive_sms_sender_raises_an_error_if_attempting_to_archive_an_inbound_number(notify_db_session, is_default):
    service = create_service_with_inbound_number(inbound_number='7654321')
    dao_add_sms_sender_for_service(service.id, 'second', is_default=True)

    inbound_number = next(x for x in service.service_sms_senders if x.inbound_number_id)

    # regardless of whether inbound number is default or not, can't delete it
    dao_update_service_sms_sender(service.id, inbound_number.id, is_default=is_default)

    with pytest.raises(ArchiveValidationError) as e:
        archive_sms_sender(
            service_id=service.id,
            sms_sender_id=inbound_number.id
        )

    assert 'You cannot delete an inbound number' in str(e.value)
    assert not inbound_number.archived


class TestGetSmsSenderByServiceIdAndNumber:

    def test_returns_none_if_no_matching_service_id(self, db_session):
        service_with_sms_sender = create_service(service_name="Service one")
        sms_sender = ServiceSmsSender(sms_sender='+15551234567', service_id=service_with_sms_sender.id)
        db_session.add(sms_sender)
        db_session.commit()

        service_without_sms_sender = create_service(service_name="Service two")
        found_sms_sender = dao_get_sms_sender_by_service_id_and_number(
            service_id=service_without_sms_sender.id,
            number='+15551234567'
        )

        assert found_sms_sender is None

    def test_returns_none_if_no_matching_number(self, db_session):
        service = create_service()
        sms_sender = ServiceSmsSender(sms_sender='+15551234567', service_id=service.id)
        db_session.add(sms_sender)
        db_session.commit()

        found_sms_sender = dao_get_sms_sender_by_service_id_and_number(service_id=service.id, number='+15557654321')

        assert found_sms_sender is None

    def test_returns_sms_sender_if_matching_service_and_number(self, db_session):
        service = create_service()
        sms_sender = ServiceSmsSender(sms_sender='+15551234567', service_id=service.id)
        db_session.add(sms_sender)
        db_session.commit()

        found_sms_sender = dao_get_sms_sender_by_service_id_and_number(service_id=service.id, number='+15551234567')

        assert found_sms_sender is sms_sender
