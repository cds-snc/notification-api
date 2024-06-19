from tests import create_authorization_header
from tests.app.conftest import create_sample_template, create_template_category


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
        "/template/category",
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


def test_get_template_category_by_id(client, sample_template_category):
    auth_header = create_authorization_header()
    response = client.get(
        f"/template/category/{sample_template_category.id}",
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
    template = create_sample_template(notify_db, notify_db_session, template_category=sample_template_category)

    auth_header = create_authorization_header()
    response = client.get(
        f"/template/category/{template.id}",
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


def test_get_template_categories(client, notify_db, notify_db_session):
    tc_hidden = create_template_category(notify_db, notify_db_session, name_en="hidden", name_fr="hidden(fr)", hidden=True)
    tc_not_hidden = create_template_category(
        notify_db, notify_db_session, name_en="not hidden", name_fr="not hidden(fr)", hidden=False
    )

    auth_header = create_authorization_header()
    response = client.get(
        "/template/category",
        headers=[("Content-Type", "application/json"), auth_header],
    )

    assert response.status_code == 200
    assert len(response.json["template_categories"]) == 2
