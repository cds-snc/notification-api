import pytest
from app.dao.template_categories_dao import (
    dao_create_template_category,
    dao_get_all_template_categories,
    dao_get_template_category_by_id,
    dao_get_template_category_by_template_id,
    dao_update_template_category,
)
from app.dao.templates_dao import dao_create_template
from app.models import BULK, NORMAL, Template, TemplateCategory
from tests.app.conftest import create_sample_template

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

def test_dao_get_all_template_categories_no_filtering(notify_db_session):
    # Insert categories into the database
    template_category1 = TemplateCategory(
        name_en="english",
        name_fr="french",
        description_en="english description",
        description_fr="french description",
        sms_process_type="normal",
        email_process_type="normal",
        hidden=False,
    )
    dao_create_template_category(template_category1)

    template_category2 = TemplateCategory(
        name_en="english2",
        name_fr="french2",
        description_en="english description2",
        description_fr="french description2",
        sms_process_type="bulk",
        email_process_type="bulk",
        hidden=False,
    )
    dao_create_template_category(template_category2)

    # Retrieve categories with no filters
    retrieved_categories = dao_get_all_template_categories()

    # Assertions
    assert len(retrieved_categories) == 2
    assert template_category1 in retrieved_categories
    assert template_category2 in retrieved_categories


@pytest.mark.parametrize(
    "template_type, hidden, expected_count, categories_to_insert",
    [
        # Filter by template type SMS
        ("sms", None, 2, [
            {
                "name_en": "english",
                "name_fr": "french",
                "sms_process_type": "normal",
                "email_process_type": "normal",
                "hidden": False,
            },
            {
                "name_en": "english2",
                "name_fr": "french2",
                "sms_process_type": "bulk",
                "email_process_type": "bulk",
                "hidden": False,
            },
        ]),

        # Filter by template type email
        ("email", None, 2, [
            {
                "name_en": "english",
                "name_fr": "french",
                "sms_process_type": "normal",
                "email_process_type": "normal",
                "hidden": False,
            },
            {
                "name_en": "english2",
                "name_fr": "french2",
                "sms_process_type": "bulk",
                "email_process_type": "bulk",
                "hidden": False,
            },
        ]),

        # Filter by hidden False
        (None, False, 1, [
            {
                "name_en": "english",
                "name_fr": "french",
                "description_en": "english description",
                "description_fr": "french description",
                "sms_process_type": "normal",
                "email_process_type": "normal",
                "hidden": False,
            },
            {
                "name_en": "english2",
                "name_fr": "french2",
                "description_en": "english description2",
                "description_fr": "french description2",
                "sms_process_type": "bulk",
                "email_process_type": "bulk",
                "hidden": True,
            },
        ]),

        # Filter by hidden True
        (None, True, 2, [
            {
                "name_en": "english",
                "name_fr": "french",
                "description_en": "english description",
                "description_fr": "french description",
                "sms_process_type": "normal",
                "email_process_type": "normal",
                "hidden": False,
            },
            {
                "name_en": "english2",
                "name_fr": "french2",
                "description_en": "english description2",
                "description_fr": "french description2",
                "sms_process_type": "bulk",
                "email_process_type": "bulk",
                "hidden": True,
            },
        ]),

        # Filter by template type SMS and hidden False
        ("sms", False, 1, [
            {
                "name_en": "english",
                "name_fr": "french",
                "description_en": "english description",
                "description_fr": "french description",
                "sms_process_type": "normal",
                "email_process_type": "normal",
                "hidden": False,
            },
            {
                "name_en": "english2",
                "name_fr": "french2",
                "description_en": "english description2",
                "description_fr": "french description2",
                "sms_process_type": "bulk",
                "email_process_type": "bulk",
                "hidden": True,
            },
        ]),

        # Filter by template type email and hidden True
        ("email", True, 2, [
            {
                "name_en": "english",
                "name_fr": "french",
                "description_en": "english description",
                "description_fr": "french description",
                "sms_process_type": "normal",
                "email_process_type": "normal",
                "hidden": False,
            },
            {
                "name_en": "english2",
                "name_fr": "french2",
                "description_en": "english description2",
                "description_fr": "french description2",
                "sms_process_type": "bulk",
                "email_process_type": "bulk",
                "hidden": True,
            },
        ]),
    ]
)
def test_get_all_template_categories(template_type, hidden, expected_count, categories_to_insert, notify_db, notify_db_session):
    # Insert categories into the database
    for category_data in categories_to_insert:
        template_category = TemplateCategory(**category_data)
        dao_create_template_category(template_category)

        # Email
        create_sample_template(notify_db, notify_db_session, template_type='email', template_category=template_category)
        # SMS
        create_sample_template(notify_db, notify_db_session, template_type='sms', template_category=template_category)

    # Retrieve categories with the specified filters
    retrieved_categories = dao_get_all_template_categories(template_type=template_type, hidden=hidden)

    # Assertions
    assert len(retrieved_categories) == expected_count
