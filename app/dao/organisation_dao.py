from sqlalchemy import desc, func, select

from app import db
from app.dao.dao_utils import transactional, version_class
from app.models import Domain, Organisation, Service


def dao_count_organsations_with_live_services():
    # Endpoint is unused, faked data
    return 0


def dao_get_organisation_by_id(organisation_id):
    stmt = select(Organisation).where(Organisation.id == organisation_id)
    return db.session.scalars(stmt).one()


def dao_get_organisation_by_email_address(email_address):
    # Endpoint is unused, query to be removed when endpoint is removed
    email_address = email_address.lower().replace('.gsi.gov.uk', '.gov.uk')

    stmt = select(Domain).order_by(desc(func.char_length(Domain.domain)))
    for domain in db.session.scalars(stmt).all():
        if email_address.endswith('@{}'.format(domain.domain)) or email_address.endswith('.{}'.format(domain.domain)):
            stmt = select(Organisation).where(Organisation.id == domain.organisation_id)
            return db.session.scalars(stmt).one()

    return None


@transactional
def dao_create_organisation(organisation):
    db.session.add(organisation)


@transactional
@version_class(Service)
def dao_add_service_to_organisation(
    service,
    organisation_id,
):
    organisation = db.session.scalars(select(Organisation).where(Organisation.id == organisation_id)).one()

    service.organisation_id = organisation_id
    service.organisation_type = organisation.organisation_type
    service.crown = organisation.crown

    db.session.add(service)
