import pytest

from app.dao.inbound_numbers_dao import (
    dao_get_inbound_numbers,
    dao_get_inbound_numbers_for_service,
    dao_get_available_inbound_numbers,
    dao_set_inbound_number_active_flag,
    dao_create_inbound_number,
    dao_update_inbound_number,
)
from app.models import InboundNumber

from tests.app.db import create_service, create_inbound_number
from tests.app.factories.inbound_number import sample_inbound_number


def test_get_inbound_numbers(notify_db_session):
    notify_db_session.session.query(InboundNumber).delete()

    inbound_number_one = sample_inbound_number()
    inbound_number_two = sample_inbound_number()

    notify_db_session.session.add(inbound_number_one)
    notify_db_session.session.add(inbound_number_two)
    notify_db_session.session.commit()

    inbound_numbers = dao_get_inbound_numbers()

    assert inbound_number_one in inbound_numbers
    assert inbound_number_two in inbound_numbers


class TestGetAvailableInboundNumbers:
    def test_gets_available_inbound_number(self, notify_db, notify_db_session):
        inbound_number = create_inbound_number(number='1', url_endpoint='https://example.foo', self_managed=True)

        res = dao_get_available_inbound_numbers()

        assert len(res) == 1
        assert res[0] == inbound_number
        assert hasattr(res[0], 'url_endpoint')
        assert hasattr(res[0], 'self_managed') and isinstance(res[0].self_managed, bool) and res[0].self_managed

    def test_after_setting_service_id_that_inbound_number_is_unavailable(
        self, notify_db, notify_db_session, sample_inbound_numbers
    ):
        service = create_service(service_name='test service')
        numbers = dao_get_available_inbound_numbers()

        assert len(numbers) == 1

        numbers[0].service = service

        res = dao_get_available_inbound_numbers()

        assert len(res) == 0


class TestSetInboundNumberActiveFlag:
    @pytest.mark.parametrize('active', [True, False])
    def test_set_inbound_number_active_flag(self, notify_db_session, active):
        inbound_number = sample_inbound_number()
        notify_db_session.session.add(inbound_number)
        notify_db_session.session.commit()

        dao_set_inbound_number_active_flag(inbound_number.id, active=active)

        inbound_number_from_db = InboundNumber.query.filter(InboundNumber.id == inbound_number.id).first()

        assert inbound_number_from_db.active is active


def test_create_inbound_number(notify_db_session):
    notify_db_session.session.query(InboundNumber).delete()

    inbound_number = sample_inbound_number()
    dao_create_inbound_number(inbound_number)

    created_in_database = notify_db_session.session.query(InboundNumber).one()
    assert created_in_database == inbound_number


class TestUpdateInboundNumber:
    @pytest.fixture
    def existing_inbound_number(self, notify_db_session):
        inbound_number = sample_inbound_number()
        notify_db_session.session.add(inbound_number)
        notify_db_session.session.commit()
        return inbound_number

    def test_updates_number(self, existing_inbound_number):
        dao_update_inbound_number(existing_inbound_number.id, number='new-number')

        assert InboundNumber.query.get(existing_inbound_number.id).number == 'new-number'

    def test_updates_provider(self, existing_inbound_number):
        dao_update_inbound_number(existing_inbound_number.id, provider='new-provider')

        assert InboundNumber.query.get(existing_inbound_number.id).provider == 'new-provider'

    def test_updates_service_id(self, existing_inbound_number):
        new_service_id = create_service(service_name='new service').id
        dao_update_inbound_number(existing_inbound_number.id, service_id=new_service_id)

        assert InboundNumber.query.get(existing_inbound_number.id).service_id == new_service_id

    def test_updates_active(self, existing_inbound_number):
        dao_update_inbound_number(existing_inbound_number.id, active=False)

        assert not InboundNumber.query.get(existing_inbound_number.id).active

    def test_does_not_update_unknown_attribute(self, existing_inbound_number):
        with pytest.raises(Exception):
            dao_update_inbound_number(existing_inbound_number.id, some_attribute_that_does_not_exist='value')

    def test_returns_updated_inbound_number(self, existing_inbound_number):
        updated = dao_update_inbound_number(existing_inbound_number.id, number='new-number')
        assert updated.number == 'new-number'


class TestGetInboundNumbersForService:
    def test_gets_empty_list_when_no_inbound_numbers_for_service(self, notify_db_session, sample_service):
        notify_db_session.session.query(InboundNumber).delete()
        assert dao_get_inbound_numbers_for_service(sample_service.id) == []

    def test_gets_inbound_numbers_for_service(self, notify_db_session, sample_service):
        notify_db_session.session.query(InboundNumber).delete()
        inbound_number_one = sample_inbound_number(number='555', service=sample_service)
        inbound_number_two = sample_inbound_number(number='111', service=sample_service)

        retrieved_inbound_numbers = dao_get_inbound_numbers_for_service(sample_service.id)
        assert inbound_number_one in retrieved_inbound_numbers
        assert inbound_number_two in retrieved_inbound_numbers
