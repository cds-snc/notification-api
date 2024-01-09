from app import db
from app.dao.dao_utils import transactional
from app.models import ServiceLetterContact, Template
from sqlalchemy import desc, select, update


def dao_get_letter_contacts_by_service_id(service_id):
    stmt = (
        select(ServiceLetterContact)
        .where(ServiceLetterContact.service_id == service_id, ServiceLetterContact.archived.is_(False))
        .order_by(desc(ServiceLetterContact.is_default), desc(ServiceLetterContact.created_at))
    )

    return db.session.scalars(stmt).all()


def dao_get_letter_contact_by_id(
    service_id,
    letter_contact_id,
):
    stmt = select(ServiceLetterContact).where(
        ServiceLetterContact.service_id == service_id,
        ServiceLetterContact.id == letter_contact_id,
        ServiceLetterContact.archived.is_(False),
    )

    return db.session.scalars(stmt).one()


@transactional
def add_letter_contact_for_service(
    service_id,
    contact_block,
    is_default,
):
    old_default = _get_existing_default(service_id)
    if is_default:
        _reset_old_default_to_false(old_default)

    new_letter_contact = ServiceLetterContact(service_id=service_id, contact_block=contact_block, is_default=is_default)
    db.session.add(new_letter_contact)
    return new_letter_contact


@transactional
def update_letter_contact(
    service_id,
    letter_contact_id,
    contact_block,
    is_default,
):
    old_default = _get_existing_default(service_id)
    # if we want to make this the default, ensure there are no other existing defaults
    if is_default:
        _reset_old_default_to_false(old_default)

    letter_contact_update = db.session.get(ServiceLetterContact, letter_contact_id)
    letter_contact_update.contact_block = contact_block
    letter_contact_update.is_default = is_default
    db.session.add(letter_contact_update)
    return letter_contact_update


@transactional
def archive_letter_contact(
    service_id,
    letter_contact_id,
):
    db.session.execute(
        update(Template)
        .where(Template.service_letter_contact_id == letter_contact_id)
        .values(service_letter_contact_id=None)
    )

    stmt = select(ServiceLetterContact).where(
        ServiceLetterContact.id == letter_contact_id, ServiceLetterContact.service_id == service_id
    )

    letter_contact_to_archive = db.session.scalars(stmt).one()
    letter_contact_to_archive.archived = True
    db.session.add(letter_contact_to_archive)
    return letter_contact_to_archive


def _get_existing_default(service_id):
    old_defaults = [x for x in dao_get_letter_contacts_by_service_id(service_id=service_id) if x.is_default]

    if len(old_defaults) == 0:
        return None

    if len(old_defaults) == 1:
        return old_defaults[0]

    raise Exception(
        'There should only be one default letter contact for each service. Service {} has {}'.format(
            service_id, len(old_defaults)
        )
    )


def _reset_old_default_to_false(old_default):
    if old_default:
        old_default.is_default = False
        db.session.add(old_default)
