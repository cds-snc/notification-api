import pytest

from app.dao.inbound_numbers_dao import (
    dao_create_inbound_number,
    dao_get_available_inbound_numbers,
    dao_get_inbound_numbers,
    dao_get_inbound_numbers_for_service,
    dao_set_inbound_number_active_flag,
    dao_update_inbound_number,
)
from app.models import InboundNumber


def test_get_inbound_numbers(notify_api, sample_inbound_number):
    inbound_number_one = sample_inbound_number()
    inbound_number_two = sample_inbound_number()
    inbound_numbers = dao_get_inbound_numbers()

    assert inbound_number_one in inbound_numbers
    assert inbound_number_two in inbound_numbers


@pytest.mark.serial
class TestGetAvailableInboundNumbers:
    def test_gets_available_inbound_number(self, sample_inbound_number):
        inbound_number = sample_inbound_number(url_endpoint='https://example.foo', self_managed=True)
        # serial method
        res = dao_get_available_inbound_numbers()

        assert len(res) == 1
        assert res[0] == inbound_number
        assert hasattr(res[0], 'url_endpoint')
        assert hasattr(res[0], 'self_managed') and isinstance(res[0].self_managed, bool) and res[0].self_managed

    def test_after_setting_service_id_that_inbound_number_is_unavailable(self, sample_service, sample_inbound_numbers):
        assert isinstance(sample_inbound_numbers, list) and len(sample_inbound_numbers) == 3
        assert (
            sample_inbound_numbers[0].service is None
            and sample_inbound_numbers[1].service is not None
            and sample_inbound_numbers[2].service is not None
        )
        # serial method
        numbers = dao_get_available_inbound_numbers()

        assert len(numbers) == 1

        service = sample_service()
        numbers[0].service = service

        res = dao_get_available_inbound_numbers()

        assert len(res) == 0


class TestSetInboundNumberActiveFlag:
    @pytest.mark.parametrize('active', [True, False])
    def test_set_inbound_number_active_flag(self, notify_db_session, active, sample_inbound_number):
        inbound_number = sample_inbound_number()
        dao_set_inbound_number_active_flag(inbound_number.id, active=active)
        inbound_number_from_db = notify_db_session.session.get(InboundNumber, inbound_number.id)
        assert inbound_number_from_db.active is active


def test_create_inbound_number(notify_db_session):
    inbound_number = InboundNumber(number=1, provider='test')

    dao_create_inbound_number(inbound_number)
    created_in_database = notify_db_session.session.get(InboundNumber, inbound_number.id)

    try:
        assert created_in_database.id == inbound_number.id
    finally:
        # Teardown
        notify_db_session.session.delete(inbound_number)
        notify_db_session.session.commit()


class TestUpdateInboundNumber:
    @pytest.fixture
    def existing_inbound_number(self, sample_inbound_number):
        return sample_inbound_number()

    def test_updates_number(self, notify_db_session, existing_inbound_number):
        dao_update_inbound_number(existing_inbound_number.id, number='new-number')

        assert notify_db_session.session.get(InboundNumber, existing_inbound_number.id).number == 'new-number'

    def test_updates_provider(self, notify_db_session, existing_inbound_number):
        dao_update_inbound_number(existing_inbound_number.id, provider='new-provider')

        assert notify_db_session.session.get(InboundNumber, existing_inbound_number.id).provider == 'new-provider'

    def test_updates_service_id(self, notify_db_session, existing_inbound_number, sample_service):
        new_service_id = sample_service(service_name='new service').id
        dao_update_inbound_number(existing_inbound_number.id, service_id=new_service_id)

        assert notify_db_session.session.get(InboundNumber, existing_inbound_number.id).service_id == new_service_id

    def test_updates_active(self, notify_db_session, existing_inbound_number):
        dao_update_inbound_number(existing_inbound_number.id, active=False)

        assert not notify_db_session.session.get(InboundNumber, existing_inbound_number.id).active

    def test_does_not_update_unknown_attribute(self, existing_inbound_number):
        with pytest.raises(Exception):
            dao_update_inbound_number(existing_inbound_number.id, some_attribute_that_does_not_exist='value')

    def test_returns_updated_inbound_number(self, existing_inbound_number, worker_id):
        updated = dao_update_inbound_number(existing_inbound_number.id, number=worker_id)
        assert updated.number == worker_id


class TestGetInboundNumbersForService:
    def test_gets_empty_list_when_no_inbound_numbers_for_service(self, sample_service):
        assert dao_get_inbound_numbers_for_service(sample_service().id) == []

    def test_gets_inbound_numbers_for_service(self, sample_service, sample_inbound_number):
        service = sample_service()
        inbound_number_one = sample_inbound_number(number='555', service_id=service.id)
        inbound_number_two = sample_inbound_number(number='111', service_id=service.id)

        retrieved_inbound_numbers = dao_get_inbound_numbers_for_service(service.id)
        assert inbound_number_one in retrieved_inbound_numbers
        assert inbound_number_two in retrieved_inbound_numbers
