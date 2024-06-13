from app.dao.template_categories_dao import (
    dao_create_template_category,
    dao_get_all_template_categories,
    dao_get_template_category_by_id,
    dao_get_template_category_by_template_id,
    dao_update_template_category,
)
from app.dao.templates_dao import dao_create_template
from app.models import BULK, NORMAL, Template, TemplateCategory


def test_create_template_category(notify_db_session):
    data = {
        "name_en": "english",
        "name_fr": "french",
        "description_en": "english description",
        "description_fr": "french description",
        "sms_process_type": NORMAL,
        "email_process_type": NORMAL,
        "hidden": False,
    }

    template_category = TemplateCategory(**data)
    dao_create_template_category(template_category)

    assert TemplateCategory.query.count() == 1
    assert len(dao_get_all_template_categories()) == 1


def test_update_template_category(notify_db_session):
    data = {
        "name_en": "english",
        "name_fr": "french",
        "description_en": "english description",
        "description_fr": "french description",
        "sms_process_type": NORMAL,
        "email_process_type": NORMAL,
        "hidden": False,
    }

    template_category = TemplateCategory(**data)
    dao_create_template_category(template_category)

    template_category.name_en = "new english"
    template_category.name_fr = "new french"
    template_category.description_en = "new english description"
    template_category.description_fr = "new french description"
    template_category.sms_process_type = BULK
    template_category.email_process_type = BULK
    template_category.hidden = True
    dao_update_template_category(template_category)

    assert TemplateCategory.query.count() == 1
    assert len(dao_get_all_template_categories()) == 1
    assert dao_get_all_template_categories()[0].name_en == "new english"
    assert dao_get_all_template_categories()[0].name_fr == "new french"
    assert dao_get_all_template_categories()[0].description_en == "new english description"
    assert dao_get_all_template_categories()[0].description_fr == "new french description"
    assert dao_get_all_template_categories()[0].sms_process_type == BULK
    assert dao_get_all_template_categories()[0].email_process_type == BULK
    assert dao_get_all_template_categories()[0].hidden
    assert dao_get_all_template_categories()[0].id == template_category.id


def test_get_template_category_by_template_id(notify_db_session, sample_service, sample_user):
    category_data = {
        "name_en": "english",
        "name_fr": "french",
        "description_en": "english description",
        "description_fr": "french description",
        "sms_process_type": NORMAL,
        "email_process_type": NORMAL,
        "hidden": False,
    }

    template_category = TemplateCategory(**category_data)
    dao_create_template_category(template_category)

    template_data = {
        "name": "Sample Template",
        "template_type": "email",
        "content": "Template content",
        "service": sample_service,
        "created_by": sample_user,
    }

    template = Template(**template_data)
    template.template_category = template_category
    dao_create_template(template)

    assert dao_get_template_category_by_template_id(template.id) == template_category


def test_get_template_category_by_id(notify_db_session):
    data = {
        "name_en": "english",
        "name_fr": "french",
        "description_en": "english description",
        "description_fr": "french description",
        "sms_process_type": NORMAL,
        "email_process_type": NORMAL,
        "hidden": False,
    }

    template_category = TemplateCategory(**data)
    dao_create_template_category(template_category)

    assert dao_get_template_category_by_id(template_category.id) == template_category


def test_get_all_template_categories(notify_db_session):
    data1 = {
        "name_en": "english",
        "name_fr": "french",
        "description_en": "english description",
        "description_fr": "french description",
        "sms_process_type": "normal",
        "email_process_type": "normal",
        "hidden": False,
    }

    data2 = {
        "name_en": "english2",
        "name_fr": "french2",
        "description_en": "english description2",
        "description_fr": "french description2",
        "sms_process_type": BULK,
        "email_process_type": BULK,
        "hidden": True,
    }

    template_category1 = TemplateCategory(**data1)
    template_category2 = TemplateCategory(**data2)
    dao_create_template_category(template_category1)
    dao_create_template_category(template_category2)

    assert len(dao_get_all_template_categories()) == 2
    assert dao_get_all_template_categories()[0].name_en == "english"
    assert dao_get_all_template_categories()[0].name_fr == "french"
    assert dao_get_all_template_categories()[0].description_en == "english description"
    assert dao_get_all_template_categories()[0].description_fr == "french description"
    assert dao_get_all_template_categories()[0].sms_process_type == NORMAL
    assert dao_get_all_template_categories()[0].email_process_type == NORMAL
    assert not dao_get_all_template_categories()[0].hidden
    assert dao_get_all_template_categories()[1].name_en == "english2"
    assert dao_get_all_template_categories()[1].name_fr == "french2"
    assert dao_get_all_template_categories()[1].description_en == "english description2"
    assert dao_get_all_template_categories()[1].description_fr == "french description2"
    assert dao_get_all_template_categories()[1].sms_process_type == BULK
    assert dao_get_all_template_categories()[1].email_process_type == BULK
    assert dao_get_all_template_categories()[1].hidden
