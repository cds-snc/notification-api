import uuid
from app import db
from app.constants import LETTER_TYPE, SECOND_CLASS
from app.dao.dao_utils import (
    transactional,
    version_class,
    VersionOptions,
)
from app.dao.users_dao import get_user_by_id
from app.models import (
    Template,
    TemplateHistory,
    TemplateRedacted,
)
from datetime import datetime
from flask import current_app
from sqlalchemy import asc, desc, func, select, update


@transactional
@version_class(VersionOptions(Template, history_class=TemplateHistory))
def dao_create_template(template):
    template.id = template.id or uuid.uuid4()  # must be set now so version history model can use same id
    template.archived = False

    redacted_dict = {
        'template': template,
        'redact_personalisation': False,
    }
    if template.created_by:
        redacted_dict.update({'updated_by': template.created_by})
    else:
        redacted_dict.update({'updated_by_id': template.created_by_id})

    template.template_redacted = TemplateRedacted(**redacted_dict)

    db.session.add(template)


@transactional
@version_class(VersionOptions(Template, history_class=TemplateHistory))
def dao_update_template(template):
    if template.archived:
        template.folder = None
    db.session.add(template)


@transactional
def dao_update_template_reply_to(
    template_id,
    reply_to,
):
    stmt = (
        update(Template)
        .where(Template.id == template_id)
        .values(
            service_letter_contact_id=reply_to,
            updated_at=datetime.utcnow(),
            version=Template.version + 1,
        )
    )

    db.session.execute(stmt)

    stmt = select(Template).where(Template.id == template_id)
    template = db.session.scalars(stmt).one()

    history = TemplateHistory(
        **{
            'id': template.id,
            'name': template.name,
            'template_type': template.template_type,
            'created_at': template.created_at,
            'updated_at': template.updated_at,
            'content': template.content,
            'service_id': template.service_id,
            'subject': template.subject,
            'postage': template.postage,
            'created_by_id': template.created_by_id,
            'version': template.version,
            'archived': template.archived,
            'process_type': template.process_type,
            'service_letter_contact_id': template.service_letter_contact_id,
        }
    )
    db.session.add(history)
    return template


@transactional
def dao_redact_template(
    template,
    user_id,
):
    template.template_redacted.redact_personalisation = True
    template.template_redacted.updated_at = datetime.utcnow()
    template.template_redacted.updated_by_id = user_id
    db.session.add(template.template_redacted)


def dao_get_template_by_id_and_service_id(
    template_id,
    service_id,
    version=None,
) -> Template:
    if version is None:
        stmt = select(Template).where(
            Template.id == template_id, Template.hidden.is_(False), Template.service_id == service_id
        )
    else:
        stmt = select(TemplateHistory).where(
            TemplateHistory.id == template_id,
            TemplateHistory.hidden.is_(False),
            TemplateHistory.service_id == service_id,
            TemplateHistory.version == version,
        )

    return db.session.scalars(stmt).one()


def dao_get_number_of_templates_by_service_id_and_name(
    service_id,
    template_name,
    version=None,
):
    if version is None:
        stmt = (
            select(func.count())
            .select_from(Template)
            .where(Template.hidden.is_(False), Template.service_id == service_id, Template.name == template_name)
        )
    else:
        stmt = (
            select(func.count())
            .select_from(TemplateHistory)
            .where(
                TemplateHistory.hidden.is_(False),
                TemplateHistory.service_id == service_id,
                TemplateHistory.name == template_name,
                TemplateHistory.version == version,
            )
        )

    return db.session.scalar(stmt)


def dao_get_template_by_id(
    template_id,
    version=None,
) -> Template:
    if version is None:
        stmt = select(Template).where(Template.id == template_id)
    else:
        stmt = select(TemplateHistory).where(TemplateHistory.id == template_id, TemplateHistory.version == version)

    return db.session.scalars(stmt).one()


def dao_get_all_templates_for_service(
    service_id,
    template_type=None,
):
    if template_type is None:
        stmt = (
            select(Template)
            .where(Template.service_id == service_id, Template.hidden.is_(False), Template.archived.is_(False))
            .order_by(asc(Template.name), asc(Template.template_type))
        )
    else:
        stmt = (
            select(Template)
            .where(
                Template.service_id == service_id,
                Template.template_type == template_type,
                Template.hidden.is_(False),
                Template.archived.is_(False),
            )
            .order_by(asc(Template.name), asc(Template.template_type))
        )

    return db.session.scalars(stmt).all()


def dao_get_template_versions(
    service_id,
    template_id,
):
    stmt = (
        select(TemplateHistory)
        .where(
            TemplateHistory.service_id == service_id,
            TemplateHistory.id == template_id,
            TemplateHistory.hidden.is_(False),
        )
        .order_by(desc(TemplateHistory.version))
    )

    return db.session.scalars(stmt).all()


def get_precompiled_letter_template(service_id):
    stmt = select(Template).where(
        Template.service_id == service_id, Template.template_type == LETTER_TYPE, Template.hidden.is_(True)
    )

    template = db.session.scalar(stmt)

    if template is not None:
        return template

    template = Template(
        name='Pre-compiled PDF',
        created_by=get_user_by_id(current_app.config['NOTIFY_USER_ID']),
        service_id=service_id,
        template_type=LETTER_TYPE,
        hidden=True,
        subject='Pre-compiled PDF',
        content='',
        postage=SECOND_CLASS,
    )

    dao_create_template(template)

    return template
