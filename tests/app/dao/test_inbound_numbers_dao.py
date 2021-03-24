import pytest
from sqlalchemy.exc import IntegrityError

from app.dao.inbound_numbers_dao import (
    dao_get_inbound_numbers,
    dao_get_inbound_number_for_service,
    dao_get_available_inbound_numbers,
    dao_set_inbound_number_to_service,
    dao_set_inbound_number_active_flag,
    dao_allocate_number_for_service,
    dao_create_inbound_number,
    dao_update_inbound_number
)
from app.models import InboundNumber

from tests.app.db import create_service, create_inbound_number


def test_get_inbound_numbers(notify_db, notify_db_session, sample_inbound_numbers):
    res = dao_get_inbound_numbers()

    assert len(res) == len(sample_inbound_numbers)
    assert res == sample_inbound_numbers


def test_get_available_inbound_numbers(notify_db, notify_db_session):
    inbound_number = create_inbound_number(number='1')

    res = dao_get_available_inbound_numbers()

    assert len(res) == 1
    assert res[0] == inbound_number


def test_set_service_id_on_inbound_number(notify_db, notify_db_session, sample_inbound_numbers):
    service = create_service(service_name='test service')
    numbers = dao_get_available_inbound_numbers()

    dao_set_inbound_number_to_service(service.id, numbers[0])

    res = InboundNumber.query.filter(InboundNumber.service_id == service.id).all()

    assert len(res) == 1
    assert res[0].service_id == service.id


def test_after_setting_service_id_that_inbound_number_is_unavailable(
        notify_db, notify_db_session, sample_inbound_numbers):
    service = create_service(service_name='test service')
    numbers = dao_get_available_inbound_numbers()

    assert len(numbers) == 1

    dao_set_inbound_number_to_service(service.id, numbers[0])

    res = dao_get_available_inbound_numbers()

    assert len(res) == 0


def test_setting_a_service_twice_will_raise_an_error(notify_db, notify_db_session):
    create_inbound_number(number='1')
    create_inbound_number(number='2')
    service = create_service(service_name='test service')
    numbers = dao_get_available_inbound_numbers()

    dao_set_inbound_number_to_service(service.id, numbers[0])

    with pytest.raises(IntegrityError) as e:
        dao_set_inbound_number_to_service(service.id, numbers[1])

    assert 'duplicate key value violates unique constraint' in str(e.value)


@pytest.mark.parametrize("active", [True, False])
def test_set_inbound_number_active_flag(notify_db, notify_db_session, sample_service, active):
    inbound_number = create_inbound_number(number='1')
    dao_set_inbound_number_to_service(sample_service.id, inbound_number)

    dao_set_inbound_number_active_flag(sample_service.id, active=active)

    inbound_number = dao_get_inbound_number_for_service(sample_service.id)

    assert inbound_number.active is active


def test_dao_allocate_number_for_service(notify_db_session):
    number = '078945612'
    inbound_number = create_inbound_number(number=number)
    service = create_service()

    updated_inbound_number = dao_allocate_number_for_service(service_id=service.id, inbound_number_id=inbound_number.id)
    assert service.get_inbound_number() == number
    assert updated_inbound_number.service_id == service.id


def test_dao_allocate_number_for_service_raises_if_inbound_number_already_taken(notify_db_session, sample_service):
    number = '078945612'
    inbound_number = create_inbound_number(number=number, service_id=sample_service.id)
    service = create_service(service_name="Service needs an inbound number")
    with pytest.raises(Exception) as exc:
        dao_allocate_number_for_service(service_id=service.id, inbound_number_id=inbound_number.id)
    assert 'is not available' in str(exc.value)


def test_dao_allocate_number_for_service_raises_if_invalid_inbound_number(notify_db_session, fake_uuid):
    service = create_service(service_name="Service needs an inbound number")
    with pytest.raises(Exception) as exc:
        dao_allocate_number_for_service(service_id=service.id, inbound_number_id=fake_uuid)
    assert 'is not available' in str(exc.value)


def test_create_inbound_number(db_session):
    db_session.query(InboundNumber).delete()

    inbound_number = InboundNumber(
        number='1234',
        provider='some-provider',
        service_id=create_service().id
    )
    dao_create_inbound_number(inbound_number)

    created_in_database = db_session.query(InboundNumber).one()
    assert created_in_database == inbound_number


class TestUpdateInboundNumber:

    @pytest.fixture
    def existing_inbound_number(self, db_session):
        inbound_number = InboundNumber(
            number='1234',
            provider='some-provider',
            service_id=create_service().id,
            active=True
        )
        db_session.add(inbound_number)
        db_session.commit()
        return inbound_number

    def test_updates_number(self, existing_inbound_number):
        dao_update_inbound_number(existing_inbound_number.id, number='new-number')

        assert InboundNumber.query.get(existing_inbound_number.id).number == 'new-number'

    def test_updates_provider(self, existing_inbound_number):
        dao_update_inbound_number(existing_inbound_number.id, provider='new-provider')

        assert InboundNumber.query.get(existing_inbound_number.id).provider == 'new-provider'

    def test_updates_service_id(self, existing_inbound_number):
        new_service_id = create_service(service_name="new service").id
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
