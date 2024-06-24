import uuid

from flask import current_app

from app import db
from app.dao.dao_utils import transactional
from app.models import Template, TemplateCategory


@transactional
def dao_create_template_category(template_category: TemplateCategory):
    if template_category.id is None:
        template_category.id = uuid.uuid4()
    db.session.add(template_category)


def dao_get_template_category_by_id(template_category_id) -> TemplateCategory:
    return TemplateCategory.query.filter_by(id=template_category_id).one()


def dao_get_template_category_by_template_id(template_id) -> TemplateCategory:
    return Template.query.filter_by(id=template_id).one().category


# TODO: Add filters: Select all template categories used by at least 1 sms/email template
def dao_get_all_template_categories(template_type=None, hidden=None):
    query = TemplateCategory.query

    if template_type is not None:
        query = query.join(Template).filter(Template.template_type == template_type)

    if hidden is not None:
        query = query.filter(TemplateCategory.hidden == hidden)

    return query.all()


@transactional
def dao_update_template_category(template_category: TemplateCategory):
    db.session.add(template_category)
    db.session.commit()


@transactional
def dao_delete_template_category_by_id(template_category_id, cascade=False):
    """
    Deletes a `TemplateCategory`. By default, if the `TemplateCategory` is associated with any `Template`, it will not be deleted.
    If the `cascade` option is specified then the category will be forcible removed:
    1. The `Category` will be dissociated from templates that use it
    2. Dissociated templates will be assigned a default category based on the sms/email process type of the category it was associated with
    previously
    3. Finally, the `Category` will be deleted

    Args:
        template_category_id (str): The id of the template_category to delete
        cascade (bool, optional): Specify whether to dissociate the category from templates that use it to force removal. Defaults to False.

    Raises:
        e: _description_
    """
    template_category = dao_get_template_category_by_id(template_category_id)
    templates = Template.query.filter_by(template_category_id=template_category_id).all()

    if templates:
        if cascade:
            try:
                for template in templates:
                    process_type = (
                        template_category.sms_process_type
                        if template.template_type == "sms"
                        else template_category.email_process_type
                    )
                    template.category = dao_get_template_category_by_id(_get_default_category_id(process_type))
                    db.session.add(template)

                db.session.delete(template_category)
            except Exception as e:
                db.session.rollback()
                raise e
    else:
        db.session.delete(template_category)
        db.session.commit()


def _get_default_category_id(process_type):
    default_categories = {
        "bulk": current_app.config["DEFAULT_TEMPLATE_CATEGORY_LOW"],
        "normal": current_app.config["DEFAULT_TEMPLATE_CATEGORY_MEDIUM"],
        "priority": current_app.config["DEFAULT_TEMPLATE_CATEGORY_HIGH"],
    }
    return default_categories.get(process_type, current_app.config["DEFAULT_TEMPLATE_CATEGORY_LOW"])
