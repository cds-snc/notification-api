import pytest

from app.models import BRANDING_ORG_NEW, EmailBranding
from tests.app.db import create_email_branding


def test_get_email_branding_options(admin_request, notify_db, notify_db_session, sample_user, sample_organisation):
    email_branding1 = EmailBranding(
        colour="#FFFFFF",
        logo="/path/image.png",
        name="Org1",
        created_by_id=sample_user.id,
        organisation_id=sample_organisation.id,
    )
    email_branding2 = EmailBranding(
        colour="#000000",
        logo="/path/other.png",
        name="Org2",
        created_by_id=sample_user.id,
    )
    notify_db.session.add_all([email_branding1, email_branding2])
    notify_db.session.commit()

    email_branding = admin_request.get("email_branding.get_email_branding_options")["email_branding"]

    assert len(email_branding) == 2
    assert {email_branding["id"] for email_branding in email_branding} == {
        str(email_branding1.id),
        str(email_branding2.id),
    }
    assert email_branding[0]["organisation_id"] == str(sample_organisation.id)
    assert email_branding[1]["organisation_id"] == ""


def test_get_email_branding_options_filter_org(admin_request, notify_db, notify_db_session, sample_user, sample_organisation):
    email_branding1 = EmailBranding(
        colour="#FFFFFF",
        logo="/path/image.png",
        name="Org1",
        created_by_id=sample_user.id,
        organisation_id=sample_organisation.id,
    )
    email_branding2 = EmailBranding(colour="#000000", logo="/path/other.png", name="Org2", created_by_id=sample_user.id)
    notify_db.session.add_all([email_branding1, email_branding2])
    notify_db.session.commit()
    email_branding = admin_request.get("email_branding.get_email_branding_options", organisation_id=sample_organisation.id)[
        "email_branding"
    ]

    assert len(email_branding) == 1
    assert email_branding[0]["organisation_id"] == str(sample_organisation.id)

    email_branding2 = admin_request.get("email_branding.get_email_branding_options")["email_branding"]

    assert len(email_branding2) == 2


def test_get_email_branding_by_id(admin_request, notify_db, sample_user, notify_db_session):
    email_branding = EmailBranding(
        colour="#FFFFFF",
        logo="/path/image.png",
        name="Some Org",
        text="My Org",
        alt_text_en="hello world",
        created_by_id=sample_user.id,
    )
    notify_db.session.add(email_branding)
    notify_db.session.commit()

    response = admin_request.get(
        "email_branding.get_email_branding_by_id",
        _expected_status=200,
        email_branding_id=email_branding.id,
    )

    assert set(response["email_branding"].keys()) == {
        "colour",
        "logo",
        "name",
        "id",
        "text",
        "brand_type",
        "organisation_id",
        "alt_text_en",
        "alt_text_fr",
        "created_by_id",
        "updated_at",
        "created_at",
        "updated_by_id",
    }
    assert response["email_branding"]["colour"] == "#FFFFFF"
    assert response["email_branding"]["logo"] == "/path/image.png"
    assert response["email_branding"]["name"] == "Some Org"
    assert response["email_branding"]["text"] == "My Org"
    assert response["email_branding"]["id"] == str(email_branding.id)
    assert response["email_branding"]["brand_type"] == str(email_branding.brand_type)
    assert response["email_branding"]["alt_text_en"] == "hello world"
    assert response["email_branding"]["alt_text_fr"] is None
    assert response["email_branding"]["created_by_id"] == str(sample_user.id)


def test_post_create_email_branding(admin_request, sample_user, notify_db_session):
    data = {
        "name": "test email_branding",
        "colour": "#0000ff",
        "logo": "/images/test_x2.png",
        "brand_type": BRANDING_ORG_NEW,
        "alt_text_en": "hello world",
        "alt_text_fr": "bonjour le monde",
        "created_by_id": str(sample_user.id),
    }
    response = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=201)
    assert data["name"] == response["data"]["name"]
    assert data["colour"] == response["data"]["colour"]
    assert data["logo"] == response["data"]["logo"]
    assert data["name"] == response["data"]["text"]
    assert data["brand_type"] == response["data"]["brand_type"]
    assert data["alt_text_en"] == response["data"]["alt_text_en"]
    assert data["alt_text_fr"] == response["data"]["alt_text_fr"]


def test_post_create_email_branding_without_brand_type_defaults(admin_request, sample_user, notify_db_session):
    data = {
        "name": "test email_branding",
        "colour": "#0000ff",
        "logo": "/images/test_x2.png",
        "alt_text_en": "hello world",
        "alt_text_fr": "bonjour le monde",
        "created_by_id": str(sample_user.id),
    }
    response = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=201)
    assert BRANDING_ORG_NEW == response["data"]["brand_type"]


def test_post_create_email_branding_without_logo_is_ok(admin_request, sample_user, notify_db_session):
    data = {
        "name": "test email_branding",
        "colour": "#0000ff",
        "alt_text_en": "hello",
        "alt_text_fr": "bonjour",
        "created_by_id": str(sample_user.id),
    }
    response = admin_request.post(
        "email_branding.create_email_branding",
        _data=data,
        _expected_status=201,
    )
    assert not response["data"]["logo"]


def test_post_create_email_branding_colour_is_valid(admin_request, sample_user, notify_db_session):
    data = {
        "logo": "images/text_x2.png",
        "name": "test branding",
        "alt_text_en": "hello",
        "alt_text_fr": "bonjour",
        "created_by_id": str(sample_user.id),
    }
    response = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=201)

    assert response["data"]["logo"] == data["logo"]
    assert response["data"]["name"] == "test branding"
    assert response["data"]["colour"] is None
    assert response["data"]["text"] == "test branding"
    assert response["data"]["alt_text_en"] == "hello"
    assert response["data"]["alt_text_fr"] == "bonjour"


def test_post_create_email_branding_with_text(admin_request, sample_user, notify_db_session):
    data = {
        "text": "text for brand",
        "logo": "images/text_x2.png",
        "name": "test branding",
        "alt_text_en": "hello",
        "alt_text_fr": "bonjour",
        "created_by_id": str(sample_user.id),
    }
    response = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=201)

    assert response["data"]["logo"] == data["logo"]
    assert response["data"]["name"] == "test branding"
    assert response["data"]["colour"] is None
    assert response["data"]["text"] == "text for brand"
    assert response["data"]["alt_text_en"] == "hello"
    assert response["data"]["alt_text_fr"] == "bonjour"


def test_post_create_email_branding_with_text_and_name(admin_request, sample_user, notify_db_session):
    data = {
        "name": "name for brand",
        "text": "text for brand",
        "logo": "images/text_x2.png",
        "alt_text_en": "hello",
        "alt_text_fr": "bonjour",
        "created_by_id": str(sample_user.id),
    }
    response = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=201)

    assert response["data"]["logo"] == data["logo"]
    assert response["data"]["name"] == "name for brand"
    assert response["data"]["colour"] is None
    assert response["data"]["text"] == "text for brand"
    assert response["data"]["alt_text_en"] == "hello"
    assert response["data"]["alt_text_fr"] == "bonjour"


def test_post_create_email_branding_with_text_as_none_and_name(admin_request, sample_user, notify_db_session):
    data = {
        "name": "name for brand",
        "text": None,
        "logo": "images/text_x2.png",
        "alt_text_en": "hello",
        "alt_text_fr": "bonjour",
        "created_by_id": str(sample_user.id),
    }
    response = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=201)

    assert response["data"]["logo"] == data["logo"]
    assert response["data"]["name"] == "name for brand"
    assert response["data"]["colour"] is None
    assert response["data"]["text"] is None
    assert response["data"]["alt_text_en"] == "hello"
    assert response["data"]["alt_text_fr"] == "bonjour"


def test_post_create_email_branding_returns_400_when_name_is_missing(admin_request, sample_user, notify_db_session):
    data = {
        "text": "some text",
        "logo": "images/text_x2.png",
        "alt_text_en": "hello",
        "alt_text_fr": "bonjour",
        "created_by_id": str(sample_user.id),
    }
    response = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=400)

    assert response["errors"][0]["message"] == "name is a required property"


def test_post_create_email_branding_returns_400_if_name_is_duplicate(admin_request, sample_user, notify_db_session):
    data = {
        "name": "niceName",
        "text": "some text",
        "logo": "images/text_x2.png",
        "alt_text_en": "hello",
        "alt_text_fr": "bonjour",
        "created_by_id": str(sample_user.id),
    }
    admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=201)
    response = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=400)

    assert response["message"] == "Email branding already exists, name must be unique."


def test_post_update_email_branding_returns_400_if_name_is_duplicate(admin_request, sample_user, notify_db_session):
    data = {
        "name": "niceName",
        "text": "some text",
        "logo": "images/text_x2.png",
        "alt_text_en": "hello",
        "alt_text_fr": "bonjour",
        "created_by_id": str(sample_user.id),
    }
    admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=201)
    data["name"] = "niceName2"
    second_branding = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=201)

    update_response = admin_request.post(
        "email_branding.update_email_branding",
        _data={"name": "niceName", "updated_by_id": str(sample_user.id)},
        email_branding_id=second_branding["data"]["id"],
        _expected_status=400,
    )

    assert update_response["message"] == "Email branding already exists, name must be unique."


@pytest.mark.parametrize(
    "data_update",
    [
        (
            {
                "name": "test email_branding 1",
            }
        ),
        (
            {
                "logo": "images/text_x3.png",
                "colour": "#ffffff",
            }
        ),
        (
            {
                "logo": "images/text_x3.png",
            }
        ),
        (
            {
                "logo": "images/text_x3.png",
            }
        ),
        (
            {
                "logo": "images/text_x3.png",
            }
        ),
    ],
)
def test_post_update_email_branding_updates_field(admin_request, sample_user, notify_db_session, data_update):
    data = {
        "name": "test email_branding",
        "logo": "images/text_x2.png",
        "alt_text_en": "hello",
        "alt_text_fr": "bonjour",
        "created_by_id": str(sample_user.id),
    }
    response = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=201)

    email_branding_id = response["data"]["id"]
    data_update.update({"updated_by_id": str(sample_user.id)})

    admin_request.post(
        "email_branding.update_email_branding",
        _data=data_update,
        email_branding_id=email_branding_id,
    )

    email_branding = EmailBranding.query.all()

    assert len(email_branding) == 1
    assert str(email_branding[0].id) == email_branding_id
    for key in data_update.keys():
        assert str(getattr(email_branding[0], key)) == data_update[key]
    assert email_branding[0].text == email_branding[0].name


@pytest.mark.parametrize(
    "data_update",
    [
        ({"text": "text email branding"}),
        ({"text": "new text", "name": "new name"}),
        ({"text": None, "name": "test name"}),
    ],
)
def test_post_update_email_branding_updates_field_with_text(admin_request, sample_user, notify_db_session, data_update):
    data = {
        "name": "test email_branding",
        "logo": "images/text_x2.png",
        "alt_text_en": "hello",
        "alt_text_fr": "bonjour",
        "created_by_id": str(sample_user.id),
    }
    response = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=201)

    email_branding_id = response["data"]["id"]
    data_update.update({"updated_by_id": str(sample_user.id)})
    admin_request.post(
        "email_branding.update_email_branding",
        _data=data_update,
        email_branding_id=email_branding_id,
    )
    data_update.update({"updated_by_id": sample_user.id})
    email_branding = EmailBranding.query.all()

    assert len(email_branding) == 1
    assert str(email_branding[0].id) == email_branding_id
    for key in data_update.keys():
        assert getattr(email_branding[0], key) == data_update[key]


def test_create_email_branding_reject_invalid_brand_type(admin_request):
    data = {"name": "test email_branding", "brand_type": "NOT A TYPE"}
    response = admin_request.post("email_branding.create_email_branding", _data=data, _expected_status=400)

    expect = (
        "brand_type NOT A TYPE is not one of "
        "[custom_logo, both_english, both_french, custom_logo_with_background_colour, no_branding]"
    )
    assert response["errors"][0]["message"] == expect


def test_update_email_branding_reject_invalid_brand_type(admin_request, sample_user, notify_db_session):
    email_branding = create_email_branding()
    data = {
        "brand_type": "NOT A TYPE",
        "created_by_id": str(sample_user.id),
    }
    response = admin_request.post(
        "email_branding.update_email_branding",
        _data=data,
        _expected_status=400,
        email_branding_id=email_branding.id,
    )

    expect = (
        "brand_type NOT A TYPE is not one of "
        "[custom_logo, both_english, both_french, custom_logo_with_background_colour, no_branding]"
    )
    assert response["errors"][0]["message"] == expect
