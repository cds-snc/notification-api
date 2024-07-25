import json
import uuid
from datetime import datetime
from typing import Union

from flask import current_app
from notifications_utils.clients.redis import template_version_cache_key
from sqlalchemy import asc, desc

from app import db, redis_store
from app.dao.dao_utils import VersionOptions, transactional, version_class
from app.dao.users_dao import get_user_by_id
from app.models import (
    LETTER_TYPE,
    SECOND_CLASS,
    Template,
    TemplateHistory,
    TemplateRedacted,
)


@transactional
@version_class(VersionOptions(Template, history_class=TemplateHistory))
def dao_create_template(template, redact_personalisation=False):
    # must be set now so version history model can use same id
    template.id = uuid.uuid4()

    redacted_dict = {
        "template": template,
        "redact_personalisation": redact_personalisation,
    }
    if template.created_by:
        redacted_dict.update({"updated_by": template.created_by})
    else:
        redacted_dict.update({"updated_by_id": template.created_by_id})

    template.template_redacted = TemplateRedacted(**redacted_dict)

    db.session.add(template)


@transactional
@version_class(VersionOptions(Template, history_class=TemplateHistory))
def dao_update_template(template):
    db.session.add(template)


@transactional
def dao_update_template_reply_to(template_id, reply_to):
    Template.query.filter_by(id=template_id).update(
        {
            "service_letter_contact_id": reply_to,
            "updated_at": datetime.utcnow(),
            "version": Template.version + 1,
        }
    )
    template = Template.query.filter_by(id=template_id).one()

    history = TemplateHistory(
        **{
            "id": template.id,
            "name": template.name,
            "template_type": template.template_type,
            "created_at": template.created_at,
            "updated_at": template.updated_at,
            "content": template.content,
            "service_id": template.service_id,
            "subject": template.subject,
            "postage": template.postage,
            "created_by_id": template.created_by_id,
            "version": template.version,
            "archived": template.archived,
            "process_type": template.process_type,
            "service_letter_contact_id": template.service_letter_contact_id,
        }
    )
    db.session.add(history)
    return template


@transactional
def dao_update_template_process_type(template_id, process_type):
    Template.query.filter_by(id=template_id).update(
        {
            "process_type": process_type,
        }
    )
    template = Template.query.filter_by(id=template_id).one()

    history = TemplateHistory(
        **{
            "id": template.id,
            "name": template.name,
            "template_type": template.template_type,
            "created_at": template.created_at,
            "updated_at": template.updated_at,
            "content": template.content,
            "service_id": template.service_id,
            "subject": template.subject,
            "postage": template.postage,
            "created_by_id": template.created_by_id,
            "version": template.version,
            "archived": template.archived,
            "process_type": template.process_type,
            "service_letter_contact_id": template.service_letter_contact_id,
        }
    )
    db.session.add(history)
    return template


@transactional
def dao_update_template_category(template_id, category_id):
    Template.query.filter_by(id=template_id).update(
        {
            "template_category_id": category_id,
            "updated_at": datetime.utcnow(),
            "version": Template.version + 1,
        }
    )

    template = Template.query.filter_by(id=template_id).one()

    history = TemplateHistory(
        **{
            "id": template.id,
            "name": template.name,
            "template_type": template.template_type,
            "created_at": template.created_at,
            "updated_at": template.updated_at,
            "content": template.content,
            "service_id": template.service_id,
            "subject": template.subject,
            "postage": template.postage,
            "created_by_id": template.created_by_id,
            "version": template.version,
            "archived": template.archived,
            "process_type": template.process_type,
            "service_letter_contact_id": template.service_letter_contact_id,
        }
    )
    db.session.add(history)
    return template


@transactional
def dao_redact_template(template, user_id):
    template.template_redacted.redact_personalisation = True
    template.template_redacted.updated_at = datetime.utcnow()
    template.template_redacted.updated_by_id = user_id
    db.session.add(template.template_redacted)


def dao_get_template_by_id_and_service_id(template_id, service_id, version=None):
    if version is not None:
        return TemplateHistory.query.filter_by(id=template_id, hidden=False, service_id=service_id, version=version).one()
    return db.on_reader().query(Template).filter_by(id=template_id, hidden=False, service_id=service_id).one()


def dao_get_template_by_id(template_id, version=None, use_cache=False) -> Union[Template, TemplateHistory]:
    if use_cache:
        # When loading a SQLAlchemy object from cache it is in the transient state.
        # We do not add it to the session. This would defeat the purpose of using the cache.
        # The reasoning being that if the object is added to the session it would be queried
        # to retrieve the latest data for that row. Since we do not want to add the object
        # to the session it means some fields such as reply_to_text would be missing
        # so we also return the cached data.
        template_cache = redis_store.get(template_version_cache_key(template_id, version))
        if template_cache:
            template_cache_decoded = json.loads(template_cache.decode("utf-8"))["data"]
            if version:
                return TemplateHistory.from_json(template_cache_decoded)
            else:
                return Template.from_json(template_cache_decoded)
    if version is not None:
        return TemplateHistory.query.filter_by(id=template_id, version=version).one()
    return Template.query.filter_by(id=template_id).one()


def dao_get_all_templates_for_service(service_id, template_type=None):
    if template_type is not None:
        return (
            Template.query.filter_by(
                service_id=service_id,
                template_type=template_type,
                hidden=False,
                archived=False,
            )
            .order_by(
                asc(Template.name),
                asc(Template.template_type),
            )
            .all()
        )

    return (
        Template.query.filter_by(service_id=service_id, hidden=False, archived=False)
        .order_by(
            asc(Template.name),
            asc(Template.template_type),
        )
        .all()
    )


def dao_get_template_versions(service_id, template_id):
    return (
        TemplateHistory.query.filter_by(
            service_id=service_id,
            id=template_id,
            hidden=False,
        )
        .order_by(desc(TemplateHistory.version))
        .all()
    )


def get_precompiled_letter_template(service_id):
    template = Template.query.filter_by(service_id=service_id, template_type=LETTER_TYPE, hidden=True).first()
    if template is not None:
        return template

    template = Template(
        name="Pre-compiled PDF",
        created_by=get_user_by_id(current_app.config["NOTIFY_USER_ID"]),
        service_id=service_id,
        template_type=LETTER_TYPE,
        hidden=True,
        subject="Pre-compiled PDF",
        content="",
        postage=SECOND_CLASS,
    )

    dao_create_template(template)

    return template
