from uuid import uuid4

from sqlalchemy import select

from app.dao.organisation_dao import (
    dao_add_service_to_organisation,
    dao_get_organisation_by_email_address,
)
from app.models import Service


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
