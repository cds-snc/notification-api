import pytest
from flask import url_for

from tests import create_authorization_header
from tests.app.conftest import create_sample_template


def test_should_create_new_template_category(client, notify_db, notify_db_session):
    data = {
        "name_en": "new english",
        "name_fr": "new french",
        "description_en": "new english description",
        "description_fr": "new french description",
        "sms_process_type": "bulk",
        "email_process_type": "bulk",
        "hidden": True,
    }
    auth_header = create_authorization_header()

    response = client.post(
        url_for("template_category.create_template_category"),
        headers=[("Content-Type", "application/json"), auth_header],
        json=data,
    )

    assert response.status_code == 201
    assert response.json["template_category"]["name_en"] == "new english"
    assert response.json["template_category"]["name_fr"] == "new french"
    assert response.json["template_category"]["description_en"] == "new english description"
    assert response.json["template_category"]["description_fr"] == "new french description"
    assert response.json["template_category"]["sms_process_type"] == "bulk"
    assert response.json["template_category"]["email_process_type"] == "bulk"
    assert response.json["template_category"]["hidden"]


@pytest.mark.parametrize("key, updated_value", [("name_en", "updated english"), ("name_fr", "updated_french")])
def test_post_create_template_categories_returns_400_if_name_is_duplicate(key, updated_value, admin_request, notify_db_session):
    data = {
        "name_en": "new english",
        "name_fr": "new french",
        "description_en": "new english description",
        "description_fr": "new french description",
        "sms_process_type": "bulk",
        "email_process_type": "bulk",
        "hidden": True,
    }
    admin_request.post("template_category.create_template_category", _data=data, _expected_status=201)
    data[key] = updated_value
    response = admin_request.post("template_category.create_template_category", _data=data, _expected_status=400)
    if key == "name_en":
        assert response["message"] == "Template category name (FR) already exists"
    else:
        assert response["message"] == "Template category name (EN) already exists"


def test_get_template_category_by_id(client, sample_template_category):
    auth_header = create_authorization_header()
    response = client.get(
        url_for("template_category.get_template_category", template_category_id=sample_template_category.id),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 200
    assert response.json["template_category"]["name_en"] == sample_template_category.name_en
    assert response.json["template_category"]["name_fr"] == sample_template_category.name_fr
    assert response.json["template_category"]["description_en"] == sample_template_category.description_en
    assert response.json["template_category"]["description_fr"] == sample_template_category.description_fr
    assert response.json["template_category"]["sms_process_type"] == sample_template_category.sms_process_type
    assert response.json["template_category"]["email_process_type"] == sample_template_category.email_process_type
    assert response.json["template_category"]["hidden"] == sample_template_category.hidden


def test_get_template_category_by_template_id(client, notify_db, notify_db_session, sample_template_category):
    category = sample_template_category
    template = create_sample_template(notify_db, notify_db_session, template_category=category)

    auth_header = create_authorization_header()
    endpoint = url_for("template_category.get_template_category_by_template_id", template_id=template.id)

    response = client.get(
        endpoint,
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 200
    assert response.json["template_category"]["name_en"] == category.name_en
    assert response.json["template_category"]["name_fr"] == category.name_fr
    assert response.json["template_category"]["description_en"] == category.description_en
    assert response.json["template_category"]["description_fr"] == category.description_fr
    assert response.json["template_category"]["sms_process_type"] == category.sms_process_type
    assert response.json["template_category"]["email_process_type"] == category.email_process_type
    assert response.json["template_category"]["hidden"] == category.hidden


@pytest.mark.parametrize(
    "template_type, hidden, expected_status_code, expected_msg",
    [
        ("invalid_template_type", True, 400, "Invalid filter 'template_type', valid template_types: 'sms', 'email'"),
        ("sms", "not_a_boolean", 200, None),
        ("email", "True", 200, None),
        ("email", "False", 200, None),
        ("email", None, 200, None),
        ("sms", "True", 200, None),
        ("sms", "False", 200, None),
        ("sms", None, 200, None),
        (None, None, 200, None),
        (None, "True", 200, None),
        (None, "False", 200, None),
    ],
)
def test_get_template_categories(
    template_type,
    hidden,
    expected_status_code,
    expected_msg,
    sample_template_category,
    client,
    notify_db,
    notify_db_session,
    mocker,
):
    auth_header = create_authorization_header()

    endpoint = url_for("template_category.get_template_categories", template_type=template_type, hidden=hidden)

    mocker.patch("app.dao.template_categories_dao.dao_get_all_template_categories", return_value=[sample_template_category])

    response = client.get(
        endpoint,
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == expected_status_code
    if not expected_status_code == 200:
        assert response.json["message"] == expected_msg


@pytest.mark.parametrize(
    "cascade, expected_status_code, expected_msg",
    [
        ("True", 204, ""),
        ("False", 400, "Cannot delete categories associated with templates. Dissociate the category from templates first."),
    ],
)
def test_delete_template_category_cascade(
    cascade,
    expected_status_code,
    expected_msg,
    client,
    mocker,
    sample_template_category_with_templates,
    populate_generic_categories,
):
    auth_header = create_authorization_header()

    endpoint = url_for(
        "template_category.delete_template_category",
        template_category_id=sample_template_category_with_templates.id,
        cascade=cascade,
    )

    response = client.delete(
        endpoint,
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == expected_status_code
    if expected_status_code == 400:
        assert response.json["message"] == expected_msg
