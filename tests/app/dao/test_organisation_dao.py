from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.dao.organisation_dao import (
    dao_add_service_to_organisation,
    dao_add_user_to_organisation,
    dao_get_organisation_by_email_address,
    dao_get_organisation_by_id,
    dao_get_organisation_by_service_id,
    dao_get_organisation_services,
    dao_get_users_for_organisation,
    dao_update_organisation,
)
from app.models import Service


def test_get_organisation_by_id_gets_correct_organisation(sample_organisation):
    organisation = sample_organisation()
    organisation_from_db = dao_get_organisation_by_id(organisation.id)
    assert organisation_from_db == organisation


def test_update_organisation_does_not_update_the_service_org_type_if_org_type_is_not_provided(
    notify_db_session,
    sample_service,
    sample_organisation,
):
    service = sample_service()
    service.organisation_type = 'other'
    organisation = sample_organisation()
    organisation.organisation_type = 'other'

    organisation.services.append(service)
    notify_db_session.session.commit()

    assert organisation.name.startswith('sample organisation')

    updated_org_name = str(uuid4())
    dao_update_organisation(organisation.id, name=updated_org_name)

    assert organisation.name == updated_org_name
    assert service.organisation_type == 'other'


def test_add_service_to_organisation(notify_db_session, sample_service, sample_organisation):
    service = sample_service()
    organisation = sample_organisation()
    assert organisation.services == []

    service.organisation_type = 'other'
    organisation.organisation_type = 'other'
    organisation.crown = False

    dao_add_service_to_organisation(service, organisation.id)

    assert len(organisation.services) == 1
    assert organisation.services[0].id == service.id

    assert service.organisation_type == organisation.organisation_type
    assert service.crown == organisation.crown

    history_model = Service.get_history_model()
    stmt = select(history_model).where(history_model.id == service.id, history_model.version == 2)
    assert notify_db_session.session.scalars(stmt).one().organisation_type == organisation.organisation_type

    assert service.organisation_id == organisation.id


def test_get_organisation_services(sample_service, sample_organisation):
    service = sample_service(service_name=f'a {uuid4()}')
    organisation = sample_organisation()
    another_service = sample_service(service_name=f'b {uuid4()}')
    another_org = sample_organisation()

    dao_add_service_to_organisation(service, organisation.id)
    dao_add_service_to_organisation(another_service, organisation.id)

    org_services = dao_get_organisation_services(organisation.id)
    other_org_services = dao_get_organisation_services(another_org.id)

    assert [service.name, another_service.name] == sorted([s.name for s in org_services])
    assert not other_org_services


def test_get_organisation_by_service_id(sample_service, sample_organisation):
    service = sample_service()
    organisation = sample_organisation()
    another_service = sample_service()
    another_org = sample_organisation()

    dao_add_service_to_organisation(service, organisation.id)
    dao_add_service_to_organisation(another_service, another_org.id)

    organisation_1 = dao_get_organisation_by_service_id(service.id)
    organisation_2 = dao_get_organisation_by_service_id(another_service.id)

    assert organisation_1 == organisation
    assert organisation_2 == another_org


def test_dao_get_users_for_organisation(sample_user, sample_organisation):
    first = sample_user(email='first@invited.com')
    second = sample_user(email='another@invited.com')
    organisation = sample_organisation()

    dao_add_user_to_organisation(organisation_id=organisation.id, user_id=first.id)
    dao_add_user_to_organisation(organisation_id=organisation.id, user_id=second.id)

    results = dao_get_users_for_organisation(organisation_id=organisation.id)

    assert len(results) == 2
    assert results[0] == first
    assert results[1] == second


def test_dao_get_users_for_organisation_returns_empty_list(sample_organisation):
    results = dao_get_users_for_organisation(organisation_id=sample_organisation().id)
    assert len(results) == 0


def test_dao_get_users_for_organisation_only_returns_active_users(sample_user, sample_organisation):
    first = sample_user()
    second = sample_user()
    organisation = sample_organisation()

    dao_add_user_to_organisation(organisation_id=organisation.id, user_id=first.id)
    dao_add_user_to_organisation(organisation_id=organisation.id, user_id=second.id)

    second.state = 'inactive'

    results = dao_get_users_for_organisation(organisation_id=organisation.id)
    assert len(results) == 1
    assert results[0] == first


def test_add_user_to_organisation_returns_user(
    sample_organisation,
    sample_user,
):
    org_user = sample_user()
    assert not org_user.organisations
    organisation = sample_organisation()

    added_user = dao_add_user_to_organisation(organisation_id=organisation.id, user_id=org_user.id)
    assert len(added_user.organisations) == 1
    assert added_user.organisations[0] == organisation


def test_add_user_to_organisation_when_user_does_not_exist(sample_organisation):
    with pytest.raises(expected_exception=SQLAlchemyError):
        dao_add_user_to_organisation(organisation_id=sample_organisation().id, user_id=uuid4())


def test_add_user_to_organisation_when_organisation_does_not_exist(sample_user):
    with pytest.raises(expected_exception=SQLAlchemyError):
        dao_add_user_to_organisation(organisation_id=uuid4(), user_id=sample_user().id)


def test_get_organisation_by_email_address_ignores_gsi_gov_uk(
    notify_db_session,
    sample_organisation,
    sample_domain,
):
    org = sample_organisation()
    domain_str = f'{str(uuid4())}example.gov.uk'
    sample_domain(domain_str, org.id)

    found_org = dao_get_organisation_by_email_address(f'test_gsi_address@{domain_str}')
    assert org == found_org
