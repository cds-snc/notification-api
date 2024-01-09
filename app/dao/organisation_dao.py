from sqlalchemy import asc, delete, desc, join, select, update
from sqlalchemy.sql.expression import func

from app import db
from app.dao.dao_utils import transactional, version_class
from app.models import (
    Organisation,
    Domain,
    InvitedOrganisationUser,
    Service,
    user_to_organisation,
)
from app.model import User


def dao_get_organisations():
    stmt = select(Organisation).order_by(desc(Organisation.active)).order_by(asc(Organisation.name))
    return db.session.scalars(stmt).all()


def dao_count_organsations_with_live_services():
    # Endpoint is unused, faked data
    return 0


def dao_get_organisation_services(organisation_id):
    return db.session.scalars(select(Organisation).where(Organisation.id == organisation_id)).one().services


def dao_get_organisation_by_id(organisation_id):
    return db.session.scalars(select(Organisation).where(Organisation.id == organisation_id)).one()


def dao_get_organisation_by_email_address(email_address):
    # Endpoint is unused, query to be removed when endpoint is removed
    email_address = email_address.lower().replace('.gsi.gov.uk', '.gov.uk')

    for domain in Domain.query.order_by(func.char_length(Domain.domain).desc()).all():
        if email_address.endswith('@{}'.format(domain.domain)) or email_address.endswith('.{}'.format(domain.domain)):
            return Organisation.query.filter_by(id=domain.organisation_id).one()

    return None


def dao_get_organisation_by_service_id(service_id):
    j_stmt = join(Organisation, Service)
    stmt = select(Organisation).select_from(j_stmt).where(Service.id == service_id)
    return db.session.scalar(stmt)


@transactional
def dao_create_organisation(organisation):
    db.session.add(organisation)


@transactional
def dao_update_organisation(
    organisation_id,
    **kwargs,
):
    # Endpoint is unused, query to be removed when endpoint is removed
    domains = kwargs.pop('domains', None)

    stmt = update(Organisation).where(Organisation.id == organisation_id).values(kwargs)
    num_updated = db.session.execute(stmt).rowcount

    if isinstance(domains, list):
        stmt = delete(Domain).where(Domain.organisation_id == organisation_id)
        db.session.execute(stmt)

        db.session.bulk_save_objects(
            [Domain(domain=domain.lower(), organisation_id=organisation_id) for domain in domains]
        )

    if 'organisation_type' in kwargs:
        organisation = db.session.get(Organisation, organisation_id)
        if organisation.services:
            _update_org_type_for_organisation_services(organisation)

    return num_updated


@version_class(Service)
def _update_org_type_for_organisation_services(organisation):
    for service in organisation.services:
        service.organisation_type = organisation.organisation_type
        db.session.add(service)


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


def dao_get_invited_organisation_user(user_id):
    return db.session.scalars(select(InvitedOrganisationUser).where(InvitedOrganisationUser.id == user_id)).one()


def dao_get_users_for_organisation(organisation_id):
    j_stmt = join(User, user_to_organisation)
    stmt = (
        select(User)
        .select_from(j_stmt)
        .where(User.state == 'active')
        .where(user_to_organisation.c.organisation_id == organisation_id)
        .order_by(User.created_at)
    )
    return db.session.scalars(stmt).all()


@transactional
def dao_add_user_to_organisation(
    organisation_id,
    user_id,
):
    organisation = dao_get_organisation_by_id(organisation_id)
    user = db.session.scalars(select(User).where(User.id == user_id)).one()
    user.organisations.append(organisation)
    db.session.add(organisation)
    return user
