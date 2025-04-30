import pytest
from flask import current_app

from app.dao.template_categories_dao import (
    dao_create_template_category,
    dao_delete_template_category_by_id,
    dao_get_all_template_categories,
    dao_get_template_category_by_id,
    dao_get_template_category_by_template_id,
    dao_update_template_category,
)
from app.dao.templates_dao import dao_create_template
from app.errors import InvalidRequest
from app.models import BULK, NORMAL, Template, TemplateCategory
from tests.app.conftest import create_sample_template


class TestCreateTemplateCategory:
    def test_create_template_category(self, sample_user, notify_db_session):
        data = {
            "name_en": "english",
            "name_fr": "french",
            "description_en": "english description",
            "description_fr": "french description",
            "sms_process_type": NORMAL,
            "email_process_type": NORMAL,
            "hidden": False,
            "sms_sending_vehicle": "short_code",
            "created_by_id": str(sample_user.id),
        }

        template_category = TemplateCategory(**data)
        dao_create_template_category(template_category)

        temp_cat = dao_get_all_template_categories()
        assert TemplateCategory.query.count() == 1
        assert len(temp_cat) == 1
        assert temp_cat[0].sms_sending_vehicle == "short_code"

    def test_create_template_category_with_no_sms_sending_vehicle(self, sample_user, notify_db_session):
        data = {
            "name_en": "english",
            "name_fr": "french",
            "description_en": "english description",
            "description_fr": "french description",
            "sms_process_type": NORMAL,
            "email_process_type": NORMAL,
            "hidden": False,
            "created_by_id": str(sample_user.id),
        }

        template_category = TemplateCategory(**data)
        dao_create_template_category(template_category)

        temp_cat = dao_get_all_template_categories()
        assert TemplateCategory.query.count() == 1
        assert len(temp_cat) == 1
        assert temp_cat[0].sms_sending_vehicle == "long_code"  # default value


@pytest.mark.parametrize(
    "category, updated_category",
    [
        (
            {
                "name_en": "english",
                "name_fr": "french",
                "description_en": "english description",
                "description_fr": "french description",
                "sms_process_type": NORMAL,
                "email_process_type": NORMAL,
                "hidden": False,
            },
            {
                "name_en": "new english",
                "name_fr": "new french",
                "description_en": "new english description",
                "description_fr": "new french description",
                "sms_process_type": BULK,
                "email_process_type": BULK,
                "hidden": True,
            },
        )
    ],
)
def test_update_template_category(notify_db_session, category, sample_user, updated_category):
    template_category = TemplateCategory(**category)
    setattr(template_category, "created_by_id", str(sample_user.id))
    dao_create_template_category(template_category)

    for key, value in updated_category.items():
        setattr(template_category, key, value)

    setattr(template_category, "updated_by_id", str(sample_user.id))

    dao_update_template_category(template_category)

    fetched_category = dao_get_all_template_categories()[0]

    assert fetched_category.id == template_category.id
    for key, value in updated_category.items():
        assert getattr(fetched_category, key) == value


@pytest.mark.parametrize(
    "category, template",
    [
        (
            {
                "name_en": "english",
                "name_fr": "french",
                "description_en": "english description",
                "description_fr": "french description",
                "sms_process_type": NORMAL,
                "email_process_type": NORMAL,
                "hidden": False,
            },
            {
                "name": "Sample Template",
                "template_type": "email",
                "content": "Template content",
            },
        )
    ],
)
def test_dao_get_template_category_by_template_id(category, template, notify_db_session, sample_service, sample_user):
    template_category = TemplateCategory(**category)
    setattr(template_category, "created_by_id", str(sample_user.id))
    dao_create_template_category(template_category)

    template = Template(**template)
    template.service = sample_service
    template.created_by = sample_user
    template.template_category = template_category
    dao_create_template(template)

    assert dao_get_template_category_by_template_id(template.id) == template_category


def test_get_template_category_by_id(notify_db_session, sample_user):
    data = {
        "name_en": "english",
        "name_fr": "french",
        "description_en": "english description",
        "description_fr": "french description",
        "sms_process_type": NORMAL,
        "email_process_type": NORMAL,
        "hidden": False,
        "created_by_id": str(sample_user.id),
    }

    template_category = TemplateCategory(**data)
    dao_create_template_category(template_category)

    assert dao_get_template_category_by_id(template_category.id) == template_category


@pytest.mark.parametrize(
    "template_type, hidden, expected_count, categories_to_insert",
    [
        (
            None,
            None,
            2,
            [
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
            ],
        ),
        # Filter by template type SMS
        (
            "sms",
            None,
            2,
            [
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
            ],
        ),
        # Filter by template type email
        (
            "email",
            None,
            2,
            [
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
            ],
        ),
        # Filter by hidden False
        (
            None,
            False,
            1,
            [
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
                    "hidden": True,
                },
            ],
        ),
        # Filter by hidden True
        (
            None,
            True,
            1,
            [
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
                    "hidden": True,
                },
            ],
        ),
        # Filter by template type SMS and hidden False
        (
            "sms",
            False,
            1,
            [
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
                    "hidden": True,
                },
            ],
        ),
        (
            "sms",
            False,
            0,
            [
                {
                    "name_en": "english",
                    "name_fr": "french",
                    "sms_process_type": "normal",
                    "email_process_type": "normal",
                    "hidden": True,
                },
                {
                    "name_en": "english2",
                    "name_fr": "french2",
                    "sms_process_type": "bulk",
                    "email_process_type": "bulk",
                    "hidden": True,
                },
            ],
        ),
        # Filter by template type email and hidden True
        (
            "email",
            True,
            1,
            [
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
                    "hidden": True,
                },
            ],
        ),
        (
            "email",
            True,
            0,
            [
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
            ],
        ),
    ],
)
def test_get_all_template_categories_with_filters(
    template_type, hidden, expected_count, categories_to_insert, notify_db, sample_user, notify_db_session
):
    for category_data in categories_to_insert:
        template_category = TemplateCategory(**category_data)
        setattr(template_category, "created_by_id", str(sample_user.id))
        dao_create_template_category(template_category)

        create_sample_template(notify_db, notify_db_session, template_type="email", template_category=template_category)
        create_sample_template(notify_db, notify_db_session, template_type="sms", template_category=template_category)

    retrieved_categories = dao_get_all_template_categories(template_type=template_type, hidden=hidden)

    assert len(retrieved_categories) == expected_count


def test_dao_delete_template_category_by_id_should_delete_category_when_no_associated_templates(
    notify_db_session, sample_template_category
):
    dao_delete_template_category_by_id(sample_template_category.id)

    assert TemplateCategory.query.count() == 0


def test_dao_delete_template_category_by_id_should_not_allow_deletion_when_associated_with_template(
    notify_db, notify_db_session, sample_template_category
):
    create_sample_template(notify_db, notify_db_session, template_category=sample_template_category)

    with pytest.raises(InvalidRequest):
        dao_delete_template_category_by_id(sample_template_category.id)

    assert TemplateCategory.query.count() == 1


def test_dao_delete_template_category_by_id_should_allow_deletion_with_cascade_when_associated_with_template(
    notify_db, notify_db_session, sample_template_category, populate_generic_categories
):
    template = create_sample_template(notify_db, notify_db_session, template_category=sample_template_category)

    dao_delete_template_category_by_id(sample_template_category.id, cascade=True)
    # 3 here because we have 3 generic defaut categories that will remain post-delete
    assert TemplateCategory.query.count() == 3
    assert str(template.template_category_id) == current_app.config["DEFAULT_TEMPLATE_CATEGORY_MEDIUM"]
