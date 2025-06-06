import json
import uuid
from datetime import date, datetime, timedelta
from functools import partial
from unittest.mock import ANY, call

import pytest
import pytest_mock
from flask import Flask, current_app, url_for
from freezegun import freeze_time
from notifications_utils.clients.redis import (
    daily_limit_cache_key,
    near_daily_limit_cache_key,
    near_email_daily_limit_cache_key,
    over_daily_limit_cache_key,
    over_email_daily_limit_cache_key,
)

from app.clients.salesforce.salesforce_engagement import ENGAGEMENT_STAGE_LIVE
from app.dao.organisation_dao import dao_add_service_to_organisation
from app.dao.service_sms_sender_dao import dao_get_sms_senders_by_service_id
from app.dao.service_user_dao import dao_get_service_user
from app.dao.services_dao import dao_remove_user_from_service
from app.dao.templates_dao import dao_redact_template
from app.dao.users_dao import save_model_user
from app.dbsetup import RoutingSQLAlchemy
from app.models import (
    EMAIL_TYPE,
    INBOUND_SMS_TYPE,
    INTERNATIONAL_SMS_TYPE,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    SMS_TYPE,
    EmailBranding,
    InboundNumber,
    Notification,
    Service,
    ServiceEmailReplyTo,
    ServicePermission,
    ServiceSmsSender,
    User,
)
from tests import create_authorization_header
from tests.app.conftest import (
    create_sample_notification,
    create_sample_notification_with_job,
    create_sample_user_service_permission,
)
from tests.app.db import (
    create_annual_billing,
    create_domain,
    create_email_branding,
    create_ft_billing,
    create_ft_notification_status,
    create_inbound_number,
    create_letter_branding,
    create_notification,
    create_organisation,
    create_reply_to_email,
    create_service,
    create_service_sms_sender,
    create_service_with_defined_sms_sender,
    create_service_with_inbound_number,
    create_template,
    create_template_folder,
    create_user,
    save_notification,
)
from tests.conftest import set_config


def test_get_service_list(client, service_factory):
    service_factory.get("one")
    service_factory.get("two")
    service_factory.get("three")
    auth_header = create_authorization_header()
    response = client.get("/service", headers=[auth_header])
    assert response.status_code == 200
    json_resp = json.loads(response.get_data(as_text=True))
    assert len(json_resp["data"]) == 3
    assert json_resp["data"][0]["name"] == "one"
    assert json_resp["data"][1]["name"] == "two"
    assert json_resp["data"][2]["name"] == "three"


def test_get_service_list_with_only_active_flag(client, service_factory):
    inactive = service_factory.get("one")
    active = service_factory.get("two")

    inactive.active = False

    auth_header = create_authorization_header()
    response = client.get("/service?only_active=True", headers=[auth_header])
    assert response.status_code == 200
    json_resp = json.loads(response.get_data(as_text=True))
    assert len(json_resp["data"]) == 1
    assert json_resp["data"][0]["id"] == str(active.id)


def test_get_service_list_with_user_id_and_only_active_flag(admin_request, sample_user, service_factory):
    other_user = create_user(email="foo@bar.gov.uk")

    inactive = service_factory.get("one", user=sample_user)
    active = service_factory.get("two", user=sample_user)
    # from other user
    service_factory.get("three", user=other_user)

    inactive.active = False

    json_resp = admin_request.get("service.get_services", user_id=sample_user.id, only_active=True)
    assert len(json_resp["data"]) == 1
    assert json_resp["data"][0]["id"] == str(active.id)


def test_get_service_list_by_user(admin_request, sample_user, service_factory):
    other_user = create_user(email="foo@bar.gov.uk")
    service_factory.get("one", sample_user)
    service_factory.get("two", sample_user)
    service_factory.get("three", other_user)

    json_resp = admin_request.get("service.get_services", user_id=sample_user.id)
    assert len(json_resp["data"]) == 2
    assert json_resp["data"][0]["name"] == "one"
    assert json_resp["data"][1]["name"] == "two"


def test_get_service_list_by_user_should_return_empty_list_if_no_services(admin_request, sample_service):
    # service is already created by sample user
    new_user = create_user(email="foo@bar.gov.uk")

    json_resp = admin_request.get("service.get_services", user_id=new_user.id)
    assert json_resp["data"] == []


def test_get_service_list_should_return_empty_list_if_no_services(admin_request):
    json_resp = admin_request.get("service.get_services")
    assert len(json_resp["data"]) == 0


def test_find_services_by_name_finds_services(notify_db, admin_request, mocker):
    service_1 = create_service(service_name="ABCDEF")
    service_2 = create_service(service_name="ABCGHT")
    mock_get_services_by_partial_name = mocker.patch(
        "app.service.rest.get_services_by_partial_name",
        return_value=[service_1, service_2],
    )
    response = admin_request.get("service.find_services_by_name", service_name="ABC")["data"]
    mock_get_services_by_partial_name.assert_called_once_with("ABC")
    assert len(response) == 2


def test_find_services_by_name_handles_no_results(notify_db, admin_request, mocker):
    mock_get_services_by_partial_name = mocker.patch("app.service.rest.get_services_by_partial_name", return_value=[])
    response = admin_request.get("service.find_services_by_name", service_name="ABC")["data"]
    mock_get_services_by_partial_name.assert_called_once_with("ABC")
    assert len(response) == 0


def test_find_services_by_name_handles_no_service_name(notify_db, admin_request, mocker):
    mock_get_services_by_partial_name = mocker.patch("app.service.rest.get_services_by_partial_name")
    admin_request.get("service.find_services_by_name", _expected_status=400)
    mock_get_services_by_partial_name.assert_not_called()


def test_get_live_services_data(sample_user, admin_request):
    org = create_organisation()

    service = create_service(go_live_user=sample_user, go_live_at=datetime(2018, 1, 1))
    service_2 = create_service(service_name="second", go_live_at=datetime(2019, 1, 1), go_live_user=sample_user)

    template = create_template(service=service)
    template2 = create_template(service=service, template_type="email")
    dao_add_service_to_organisation(service=service, organisation_id=org.id)
    create_ft_billing(
        utc_date="2019-04-20",
        notification_type="sms",
        template=template,
        service=service,
    )
    create_ft_billing(
        utc_date="2019-04-20",
        notification_type="email",
        template=template2,
        service=service,
    )

    create_annual_billing(service.id, 1, 2019)
    create_annual_billing(service_2.id, 2, 2018)

    response = admin_request.get("service.get_live_services_data")["data"]

    assert len(response) == 2
    assert response == [
        {
            "consent_to_research": None,
            "contact_email": "notify@digital.cabinet-office.gov.uk",
            "contact_mobile": "+16502532222",
            "contact_name": "Test User",
            "email_totals": 1,
            "email_volume_intent": None,
            "letter_totals": 0,
            "letter_volume_intent": None,
            "live_date": "Mon, 01 Jan 2018 00:00:00 GMT",
            "organisation_name": "test_org_1",
            "service_id": ANY,
            "service_name": "Sample service",
            "sms_totals": 1,
            "sms_volume_intent": None,
            "organisation_type": None,
            "free_sms_fragment_limit": 1,
        },
        {
            "consent_to_research": None,
            "contact_email": "notify@digital.cabinet-office.gov.uk",
            "contact_mobile": "+16502532222",
            "contact_name": "Test User",
            "email_totals": 0,
            "email_volume_intent": None,
            "letter_totals": 0,
            "letter_volume_intent": None,
            "live_date": "Tue, 01 Jan 2019 00:00:00 GMT",
            "organisation_name": None,
            "service_id": ANY,
            "service_name": "second",
            "sms_totals": 0,
            "sms_volume_intent": None,
            "organisation_type": None,
            "free_sms_fragment_limit": 2,
        },
    ]


def test_get_delivered_notification_stats_by_month_data(admin_request, sample_service):
    email_template = create_template(service=sample_service, template_type="email", template_name="b")

    create_ft_notification_status(
        utc_date=date(2019, 12, 10),
        service=sample_service,
        template=email_template,
        count=3,
    )

    response = admin_request.get("service.get_delivered_notification_stats_by_month_data")["data"]

    assert len(response) == 1
    assert sorted(list(response[0])) == ["count", "month", "notification_type"]
    first = response[0]
    assert first["month"].startswith("2019-12-01")
    assert first["notification_type"] == "email"
    assert first["count"] == 3


def test_get_delivered_notification_stats_by_month_data_without_heartbeat(notify_api, admin_request, sample_service):
    email_template = create_template(service=sample_service, template_type="email", template_name="b")

    create_ft_notification_status(
        utc_date=date(2019, 12, 10),
        service=sample_service,
        template=email_template,
        count=3,
    )
    with set_config(notify_api, "NOTIFY_SERVICE_ID", email_template.service_id):
        response = admin_request.get("service.get_delivered_notification_stats_by_month_data", filter_heartbeats=True)["data"]
        assert len(response) == 0


def test_get_service_by_id(admin_request, sample_service):
    json_resp = admin_request.get("service.get_service_by_id", service_id=sample_service.id)
    assert json_resp["data"]["name"] == sample_service.name
    assert json_resp["data"]["id"] == str(sample_service.id)
    assert not json_resp["data"]["research_mode"]
    assert json_resp["data"]["email_branding"] is None
    assert "branding" not in json_resp["data"]
    assert json_resp["data"]["prefix_sms"] is True
    assert json_resp["data"]["letter_logo_filename"] is None


@pytest.mark.parametrize("detailed", [True, False])
def test_get_service_by_id_returns_organisation_type(admin_request, sample_service, detailed):
    json_resp = admin_request.get("service.get_service_by_id", service_id=sample_service.id, detailed=detailed)
    assert json_resp["data"]["organisation_type"] is None


def test_get_service_list_has_default_permissions(admin_request, service_factory):
    service_factory.get("one")
    service_factory.get("one")
    service_factory.get("two")
    service_factory.get("three")

    json_resp = admin_request.get("service.get_services")
    assert len(json_resp["data"]) == 3
    assert all(
        set(json["permissions"])
        == set(
            [
                EMAIL_TYPE,
                SMS_TYPE,
                INTERNATIONAL_SMS_TYPE,
            ]
        )
        for json in json_resp["data"]
    )


def test_get_service_by_id_has_default_service_permissions(admin_request, sample_service):
    json_resp = admin_request.get("service.get_service_by_id", service_id=sample_service.id)

    assert set(json_resp["data"]["permissions"]) == set(
        [
            EMAIL_TYPE,
            SMS_TYPE,
            INTERNATIONAL_SMS_TYPE,
        ]
    )


def test_get_service_by_id_should_404_if_no_service(admin_request, notify_db_session):
    json_resp = admin_request.get("service.get_service_by_id", service_id=uuid.uuid4(), _expected_status=404)

    assert json_resp["result"] == "error"
    assert json_resp["message"] == "No result found"


def test_get_service_by_id_and_user(client, sample_service, sample_user):
    sample_service.reply_to_email = "something@service.com"
    create_reply_to_email(service=sample_service, email_address="new@service.com")
    auth_header = create_authorization_header()
    resp = client.get(
        "/service/{}?user_id={}".format(sample_service.id, sample_user.id),
        headers=[auth_header],
    )
    assert resp.status_code == 200
    json_resp = resp.json
    assert json_resp["data"]["name"] == sample_service.name
    assert json_resp["data"]["id"] == str(sample_service.id)


def test_get_service_by_id_should_404_if_no_service_for_user(notify_api, sample_user):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service_id = str(uuid.uuid4())
            auth_header = create_authorization_header()
            resp = client.get(
                "/service/{}?user_id={}".format(service_id, sample_user.id),
                headers=[auth_header],
            )
            assert resp.status_code == 404
            json_resp = resp.json
            assert json_resp["result"] == "error"
            assert json_resp["message"] == "No result found"


def test_get_service_by_id_returns_go_live_user_and_go_live_at(admin_request, sample_user):
    now = datetime.utcnow()
    service = create_service(user=sample_user, go_live_user=sample_user, go_live_at=now)
    json_resp = admin_request.get("service.get_service_by_id", service_id=service.id)
    assert json_resp["data"]["go_live_user"] == str(sample_user.id)
    assert json_resp["data"]["go_live_at"] == str(now)


@pytest.mark.parametrize(
    "platform_admin, expected_count_as_live",
    (
        (True, False),
        (False, True),
    ),
)
def test_create_service(admin_request, sample_user, platform_admin, expected_count_as_live, mocker):
    sample_user.platform_admin = platform_admin
    data = {
        "name": "created service",
        "user_id": str(sample_user.id),
        "message_limit": 1000,
        "sms_daily_limit": 1000,
        "restricted": False,
        "active": False,
        "email_from": "created.service",
        "created_by": str(sample_user.id),
    }

    mocked_salesforce_client = mocker.patch("app.service.rest.salesforce_client")

    json_resp = admin_request.post("service.create_service", _data=data, _expected_status=201)

    assert json_resp["data"]["id"]
    assert json_resp["data"]["name"] == "created service"
    assert json_resp["data"]["email_from"] == "created.service"
    assert not json_resp["data"]["research_mode"]
    assert json_resp["data"]["rate_limit"] == 1000
    assert json_resp["data"]["letter_branding"] is None
    assert json_resp["data"]["count_as_live"] is expected_count_as_live
    mocked_salesforce_client.engagement_create.assert_called_once()

    service_db = Service.query.get(json_resp["data"]["id"])
    assert service_db.name == "created service"

    json_resp = admin_request.get(
        "service.get_service_by_id",
        service_id=json_resp["data"]["id"],
        user_id=sample_user.id,
    )

    assert json_resp["data"]["name"] == "created service"
    assert not json_resp["data"]["research_mode"]

    service_sms_senders = ServiceSmsSender.query.filter_by(service_id=service_db.id).all()
    assert len(service_sms_senders) == 1
    assert service_sms_senders[0].sms_sender == current_app.config["FROM_NUMBER"]


@pytest.mark.parametrize(
    "domain, expected_org",
    (
        (None, False),
        ("", False),
        ("unknown.gov.uk", False),
        ("unknown-example.gov.uk", False),
        ("example.gov.uk", True),
        ("test.gov.uk", True),
        ("test.example.gov.uk", True),
    ),
)
def test_create_service_with_domain_sets_organisation(admin_request, sample_user, domain, expected_org, mocker):
    red_herring_org = create_organisation(name="Sub example")
    create_domain("specific.example.gov.uk", red_herring_org.id)
    create_domain("aaaaaaaa.example.gov.uk", red_herring_org.id)

    org = create_organisation()
    create_domain("example.gov.uk", org.id)
    create_domain("test.gov.uk", org.id)

    another_org = create_organisation(name="Another")
    create_domain("cabinet-office.gov.uk", another_org.id)
    create_domain("cabinetoffice.gov.uk", another_org.id)

    sample_user.email_address = "test@{}".format(domain)

    data = {
        "name": "created service",
        "user_id": str(sample_user.id),
        "message_limit": 1000,
        "sms_daily_limit": 1000,
        "restricted": False,
        "active": False,
        "email_from": "created.service",
        "created_by": str(sample_user.id),
        "service_domain": domain,
    }
    json_resp = admin_request.post("service.create_service", _data=data, _expected_status=201)

    if expected_org:
        assert json_resp["data"]["organisation"] == str(org.id)
    else:
        assert json_resp["data"]["organisation"] is None


def test_create_service_doesnt_inherit_branding_from_organisation(admin_request, sample_user, mocker):
    org = create_organisation()
    email_branding = create_email_branding()
    org.email_branding = email_branding
    letter_branding = create_letter_branding()
    org.letter_branding = letter_branding
    create_domain("example.gov.uk", org.id)
    sample_user.email_address = "test@example.gov.uk"

    json_resp = admin_request.post(
        "service.create_service",
        _data={
            "name": "created service",
            "user_id": str(sample_user.id),
            "message_limit": 1000,
            "sms_daily_limit": 1000,
            "restricted": False,
            "active": False,
            "email_from": "created.service",
            "created_by": str(sample_user.id),
        },
        _expected_status=201,
    )

    assert json_resp["data"]["email_branding"] is None


def test_should_not_create_service_with_missing_user_id_field(notify_api, fake_uuid):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                "email_from": "service",
                "name": "created service",
                "message_limit": 1000,
                "sms_daily_limit": 1000,
                "restricted": False,
                "active": False,
                "created_by": str(fake_uuid),
            }
            auth_header = create_authorization_header()
            headers = [("Content-Type", "application/json"), auth_header]
            resp = client.post("/service", data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert resp.status_code == 400
            assert json_resp["result"] == "error"
            assert "Missing data for required field." in json_resp["message"]["user_id"]


def test_should_error_if_created_by_missing(notify_api, sample_user):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                "email_from": "service",
                "name": "created service",
                "message_limit": 1000,
                "sms_daily_limit": 1000,
                "restricted": False,
                "active": False,
                "user_id": str(sample_user.id),
            }
            auth_header = create_authorization_header()
            headers = [("Content-Type", "application/json"), auth_header]
            resp = client.post("/service", data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert resp.status_code == 400
            assert json_resp["result"] == "error"
            assert "Missing data for required field." in json_resp["message"]["created_by"]


def test_should_not_create_service_with_missing_if_user_id_is_not_in_database(
    notify_api,
    notify_db,
    notify_db_session,
    fake_uuid,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                "email_from": "service",
                "user_id": fake_uuid,
                "name": "created service",
                "message_limit": 1000,
                "sms_daily_limit": 1000,
                "restricted": False,
                "active": False,
                "created_by": str(fake_uuid),
            }
            auth_header = create_authorization_header()
            headers = [("Content-Type", "application/json"), auth_header]
            resp = client.post("/service", data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert resp.status_code == 404
            assert json_resp["result"] == "error"
            assert json_resp["message"] == "No result found"


def test_should_not_create_service_if_missing_data(notify_api, sample_user):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {"user_id": str(sample_user.id)}
            auth_header = create_authorization_header()
            headers = [("Content-Type", "application/json"), auth_header]
            resp = client.post("/service", data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert resp.status_code == 400
            assert json_resp["result"] == "error"
            assert "Missing data for required field." in json_resp["message"]["name"]
            assert "Missing data for required field." in json_resp["message"]["message_limit"]
            # assert "Missing data for required field." in json_resp["message"]["sms_daily_limit"] # TODO: put this back in once we add sms_daily_limit to admin
            assert "Missing data for required field." in json_resp["message"]["restricted"]


def test_should_not_create_service_with_duplicate_name(notify_api, sample_user, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                "name": sample_service.name,
                "user_id": str(sample_service.users[0].id),
                "message_limit": 1000,
                "sms_daily_limit": 1000,
                "restricted": False,
                "active": False,
                "email_from": "sample.service2",
                "created_by": str(sample_user.id),
            }
            auth_header = create_authorization_header()
            headers = [("Content-Type", "application/json"), auth_header]
            resp = client.post("/service", data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert json_resp["result"] == "error"
            assert "Duplicate service name '{}'".format(sample_service.name) in json_resp["message"]["name"]


def test_create_service_should_throw_duplicate_key_constraint_for_existing_email_from(notify_api, service_factory, sample_user):
    first_service = service_factory.get("First service", email_from="first.service")
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service_name = "First SERVICE"
            data = {
                "name": service_name,
                "user_id": str(first_service.users[0].id),
                "message_limit": 1000,
                "sms_daily_limit": 1000,
                "restricted": False,
                "active": False,
                "email_from": "first.service",
                "created_by": str(sample_user.id),
            }
            auth_header = create_authorization_header()
            headers = [("Content-Type", "application/json"), auth_header]
            resp = client.post("/service", data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert json_resp["result"] == "error"
            assert "Duplicate service name '{}'".format(service_name) in json_resp["message"]["name"]


def test_update_service(client, notify_db, sample_service):
    brand = EmailBranding(
        colour="#000000", logo="justice-league.png", name="Justice League", created_by_id=sample_service.created_by.id
    )
    notify_db.session.add(brand)
    notify_db.session.commit()

    assert sample_service.email_branding is None

    data = {
        "name": "updated service name",
        "email_from": "updated.service.name",
        "created_by": str(sample_service.created_by.id),
        "email_branding": str(brand.id),
        "organisation_type": "school_or_college",
    }

    auth_header = create_authorization_header()

    resp = client.post(
        "/service/{}".format(sample_service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    result = resp.json
    assert resp.status_code == 200
    assert result["data"]["name"] == "updated service name"
    assert result["data"]["email_from"] == "updated.service.name"
    assert result["data"]["email_branding"] == str(brand.id)
    assert result["data"]["organisation_type"] == "school_or_college"


def test_cant_update_service_org_type_to_random_value(client, sample_service):
    data = {
        "name": "updated service name",
        "email_from": "updated.service.name",
        "created_by": str(sample_service.created_by.id),
        "organisation_type": "foo",
    }

    auth_header = create_authorization_header()

    resp = client.post(
        "/service/{}".format(sample_service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert resp.status_code == 500


def test_update_service_remove_email_branding(admin_request, notify_db, sample_service):
    brand = EmailBranding(
        colour="#000000", logo="justice-league.png", name="Justice League", created_by_id=sample_service.created_by.id
    )
    sample_service.email_branding = brand
    notify_db.session.commit()

    resp = admin_request.post(
        "service.update_service",
        service_id=sample_service.id,
        _data={"email_branding": None},
    )
    assert resp["data"]["email_branding"] is None


def test_update_service_change_default_branding_language(admin_request, notify_db, sample_service):
    resp = admin_request.post(
        "service.update_service",
        service_id=sample_service.id,
        _data={"default_branding_is_french": True, "updated_by_id": str(sample_service.created_by.id)},
    )

    assert resp["data"]["default_branding_is_french"] is True


def test_update_service_change_email_branding(admin_request, notify_db, sample_service):
    brand1 = EmailBranding(
        colour="#000000", logo="justice-league.png", name="Justice League", created_by_id=sample_service.created_by.id
    )
    brand2 = EmailBranding(colour="#111111", logo="avengers.png", name="Avengers", created_by_id=sample_service.created_by.id)
    notify_db.session.add_all([brand1, brand2])
    sample_service.email_branding = brand1
    notify_db.session.commit()

    resp = admin_request.post(
        "service.update_service",
        service_id=sample_service.id,
        _data={"email_branding": str(brand2.id)},
    )
    assert resp["data"]["email_branding"] == str(brand2.id)


def test_update_service_flags(client, sample_service):
    auth_header = create_authorization_header()
    resp = client.get("/service/{}".format(sample_service.id), headers=[auth_header])
    json_resp = resp.json
    assert resp.status_code == 200
    assert json_resp["data"]["name"] == sample_service.name
    assert json_resp["data"]["research_mode"] is False

    data = {"research_mode": True, "permissions": [LETTER_TYPE, INTERNATIONAL_SMS_TYPE]}

    auth_header = create_authorization_header()

    resp = client.post(
        "/service/{}".format(sample_service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    result = resp.json
    assert resp.status_code == 200
    assert result["data"]["research_mode"] is True
    assert set(result["data"]["permissions"]) == set([LETTER_TYPE, INTERNATIONAL_SMS_TYPE])


@pytest.mark.parametrize(
    "field",
    (
        "volume_email",
        "volume_sms",
        "volume_letter",
    ),
)
@pytest.mark.parametrize(
    "value, expected_status, expected_persisted",
    (
        (1234, 200, 1234),
        (None, 200, None),
        ("Aa", 400, None),
    ),
)
def test_update_service_sets_volumes(
    admin_request,
    sample_service,
    field,
    value,
    expected_status,
    expected_persisted,
):
    admin_request.post(
        "service.update_service",
        service_id=sample_service.id,
        _data={
            field: value,
        },
        _expected_status=expected_status,
    )
    assert getattr(sample_service, field) == expected_persisted


@pytest.mark.parametrize(
    "value, expected_status, expected_persisted",
    (
        (True, 200, True),
        (False, 200, False),
        ("Yes", 200, True),
        ("No", 200, False),
        ("Oui", 400, None),
        ("Non", 400, None),
    ),
)
def test_update_service_sets_research_consent(
    admin_request,
    sample_service,
    value,
    expected_status,
    expected_persisted,
):
    assert sample_service.consent_to_research is None
    admin_request.post(
        "service.update_service",
        service_id=sample_service.id,
        _data={
            "consent_to_research": value,
        },
        _expected_status=expected_status,
    )
    assert sample_service.consent_to_research is expected_persisted


@pytest.fixture(scope="function")
def service_with_no_permissions(notify_db, notify_db_session):
    return create_service(service_permissions=[])


def test_update_service_flags_with_service_without_default_service_permissions(client, service_with_no_permissions):
    auth_header = create_authorization_header()
    data = {
        "permissions": [LETTER_TYPE, INTERNATIONAL_SMS_TYPE],
    }

    resp = client.post(
        "/service/{}".format(service_with_no_permissions.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    result = resp.json

    assert resp.status_code == 200
    assert set(result["data"]["permissions"]) == set([LETTER_TYPE, INTERNATIONAL_SMS_TYPE])


def test_update_service_flags_will_remove_service_permissions(client, notify_db, notify_db_session):
    auth_header = create_authorization_header()

    service = create_service(service_permissions=[SMS_TYPE, EMAIL_TYPE, INTERNATIONAL_SMS_TYPE])

    assert INTERNATIONAL_SMS_TYPE in [p.permission for p in service.permissions]

    data = {"permissions": [SMS_TYPE, EMAIL_TYPE]}

    resp = client.post(
        "/service/{}".format(service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    result = resp.json

    assert resp.status_code == 200
    assert INTERNATIONAL_SMS_TYPE not in result["data"]["permissions"]

    permissions = ServicePermission.query.filter_by(service_id=service.id).all()
    assert set([p.permission for p in permissions]) == set([SMS_TYPE, EMAIL_TYPE])


def test_update_permissions_will_override_permission_flags(client, service_with_no_permissions):
    auth_header = create_authorization_header()

    data = {"permissions": [LETTER_TYPE, INTERNATIONAL_SMS_TYPE]}

    resp = client.post(
        "/service/{}".format(service_with_no_permissions.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    result = resp.json

    assert resp.status_code == 200
    assert set(result["data"]["permissions"]) == set([LETTER_TYPE, INTERNATIONAL_SMS_TYPE])


def test_update_service_permissions_will_add_service_permissions(client, sample_service):
    auth_header = create_authorization_header()

    data = {"permissions": [EMAIL_TYPE, SMS_TYPE, LETTER_TYPE]}

    resp = client.post(
        "/service/{}".format(sample_service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    result = resp.json

    assert resp.status_code == 200
    assert set(result["data"]["permissions"]) == set([SMS_TYPE, EMAIL_TYPE, LETTER_TYPE])


@pytest.mark.parametrize(
    "permission_to_add",
    [
        (EMAIL_TYPE),
        (SMS_TYPE),
        (INTERNATIONAL_SMS_TYPE),
        (LETTER_TYPE),
        (INBOUND_SMS_TYPE),
    ],
)
def test_add_service_permission_will_add_permission(client, service_with_no_permissions, permission_to_add):
    auth_header = create_authorization_header()

    data = {"permissions": [permission_to_add]}

    resp = client.post(
        "/service/{}".format(service_with_no_permissions.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )

    permissions = ServicePermission.query.filter_by(service_id=service_with_no_permissions.id).all()

    assert resp.status_code == 200
    assert [p.permission for p in permissions] == [permission_to_add]


def test_update_permissions_with_an_invalid_permission_will_raise_error(client, sample_service):
    auth_header = create_authorization_header()
    invalid_permission = "invalid_permission"

    data = {"permissions": [EMAIL_TYPE, SMS_TYPE, invalid_permission]}

    resp = client.post(
        "/service/{}".format(sample_service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    result = resp.json

    assert resp.status_code == 400
    assert result["result"] == "error"
    assert "Invalid Service Permission: '{}'".format(invalid_permission) in result["message"]["permissions"]


def test_update_permissions_with_duplicate_permissions_will_raise_error(client, sample_service):
    auth_header = create_authorization_header()

    data = {"permissions": [EMAIL_TYPE, SMS_TYPE, LETTER_TYPE, LETTER_TYPE]}

    resp = client.post(
        "/service/{}".format(sample_service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    result = resp.json

    assert resp.status_code == 400
    assert result["result"] == "error"
    assert "Duplicate Service Permission: ['{}']".format(LETTER_TYPE) in result["message"]["permissions"]


def test_update_service_research_mode_throws_validation_error(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            auth_header = create_authorization_header()
            resp = client.get("/service/{}".format(sample_service.id), headers=[auth_header])
            json_resp = resp.json
            assert resp.status_code == 200
            assert json_resp["data"]["name"] == sample_service.name
            assert not json_resp["data"]["research_mode"]

            data = {"research_mode": "dedede"}

            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}".format(sample_service.id),
                data=json.dumps(data),
                headers=[("Content-Type", "application/json"), auth_header],
            )
            result = resp.json
            assert result["message"]["research_mode"][0] == "Not a valid boolean."
            assert resp.status_code == 400


def test_should_not_update_service_with_duplicate_name(notify_api, notify_db, notify_db_session, sample_user, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service_name = "another name"
            service = create_service(service_name=service_name, user=sample_user, email_from="another.name")
            data = {"name": service_name, "created_by": str(service.created_by.id)}

            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}".format(sample_service.id),
                data=json.dumps(data),
                headers=[("Content-Type", "application/json"), auth_header],
            )
            assert resp.status_code == 400
            json_resp = resp.json
            assert json_resp["result"] == "error"
            assert "Duplicate service name '{}'".format(service_name) in json_resp["message"]["name"]


def test_should_not_update_service_with_duplicate_email_from(
    notify_api, notify_db, notify_db_session, sample_user, sample_service
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            email_from = "duplicate.name"
            service_name = "duplicate name"
            service = create_service(service_name=service_name, user=sample_user, email_from=email_from)
            data = {
                "name": service_name,
                "email_from": email_from,
                "created_by": str(service.created_by.id),
            }

            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}".format(sample_service.id),
                data=json.dumps(data),
                headers=[("Content-Type", "application/json"), auth_header],
            )
            assert resp.status_code == 400
            json_resp = resp.json
            assert json_resp["result"] == "error"
            assert (
                "Duplicate service name '{}'".format(service_name) in json_resp["message"]["name"]
                or "Duplicate service name '{}'".format(email_from) in json_resp["message"]["name"]
            )


def test_update_service_should_404_if_id_is_invalid(notify_api):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {"name": "updated service name"}

            missing_service_id = uuid.uuid4()

            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}".format(missing_service_id),
                data=json.dumps(data),
                headers=[("Content-Type", "application/json"), auth_header],
            )
            assert resp.status_code == 404


@pytest.mark.parametrize(
    "limit_field, limit_value, expected_status", [("sms_annual_limit", 1000, 200), ("email_annual_limit", 10000, 200)]
)
def test_update_service_annual_limits(
    admin_request,
    sample_service,
    limit_field,
    limit_value,
    expected_status,
    mocker,
):
    mocker.patch("app.service.rest.send_notification_to_service_users")
    redis_delete = mocker.patch("app.service.rest.redis_store.delete_hash_fields")
    admin_request.post(
        "service.update_service",
        service_id=sample_service.id,
        _data={
            limit_field: limit_value,
        },
        _expected_status=expected_status,
    )
    assert getattr(sample_service, limit_field) == limit_value
    if limit_field == "sms_annual_limit":
        assert redis_delete.call_args_list == [
            call(f"annual-limit:{sample_service.id}:status", ["near_sms_limit", "near_email_limit"]),
        ]
    if limit_field == "email_annual_limit":
        assert redis_delete.call_args_list == [
            call(f"annual-limit:{sample_service.id}:status", ["over_email_limit", "near_email_limit"]),
        ]


def test_get_users_by_service(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            user_on_service = sample_service.users[0]
            auth_header = create_authorization_header()

            resp = client.get(
                "/service/{}/users".format(sample_service.id),
                headers=[("Content-Type", "application/json"), auth_header],
            )

            assert resp.status_code == 200
            result = resp.json
            assert len(result["data"]) == 1
            assert result["data"][0]["name"] == user_on_service.name
            assert result["data"][0]["email_address"] == user_on_service.email_address
            assert result["data"][0]["mobile_number"] == user_on_service.mobile_number


def test_get_users_for_service_returns_empty_list_if_no_users_associated_with_service(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            dao_remove_user_from_service(sample_service, sample_service.users[0])
            auth_header = create_authorization_header()

            response = client.get(
                "/service/{}/users".format(sample_service.id),
                headers=[("Content-Type", "application/json"), auth_header],
            )
            result = json.loads(response.get_data(as_text=True))
            assert response.status_code == 200
            assert result["data"] == []


def test_get_users_for_service_returns_404_when_service_does_not_exist(notify_api, notify_db, notify_db_session):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            service_id = uuid.uuid4()
            auth_header = create_authorization_header()

            response = client.get(
                "/service/{}/users".format(service_id),
                headers=[("Content-Type", "application/json"), auth_header],
            )
            assert response.status_code == 404
            result = json.loads(response.get_data(as_text=True))
            assert result["result"] == "error"
            assert result["message"] == "No result found"


def test_default_permissions_are_added_for_user_service(
    notify_api, notify_db, notify_db_session, sample_service, sample_user, mocker
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                "name": "created service",
                "user_id": str(sample_user.id),
                "message_limit": 1000,
                "sms_daily_limit": 1000,
                "restricted": False,
                "active": False,
                "email_from": "created.service",
                "created_by": str(sample_user.id),
            }
            auth_header = create_authorization_header()
            headers = [("Content-Type", "application/json"), auth_header]
            resp = client.post("/service", data=json.dumps(data), headers=headers)

            json_resp = resp.json
            assert resp.status_code == 201
            assert json_resp["data"]["id"]
            assert json_resp["data"]["name"] == "created service"
            assert json_resp["data"]["email_from"] == "created.service"

            auth_header_fetch = create_authorization_header()

            resp = client.get(
                "/service/{}?user_id={}".format(json_resp["data"]["id"], sample_user.id),
                headers=[auth_header_fetch],
            )
            assert resp.status_code == 200
            header = create_authorization_header()
            response = client.get(url_for("user.get_user", user_id=sample_user.id), headers=[header])
            assert response.status_code == 200
            json_resp = json.loads(response.get_data(as_text=True))
            service_permissions = json_resp["data"]["permissions"][str(sample_service.id)]
            from app.dao.permissions_dao import default_service_permissions

            assert sorted(default_service_permissions) == sorted(service_permissions)


def test_add_existing_user_to_another_service_with_all_permissions(
    notify_api, notify_db, notify_db_session, sample_service, sample_user
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            # check which users part of service
            user_already_in_service = sample_service.users[0]
            auth_header = create_authorization_header()

            resp = client.get(
                "/service/{}/users".format(sample_service.id),
                headers=[("Content-Type", "application/json"), auth_header],
            )

            assert resp.status_code == 200
            result = resp.json
            assert len(result["data"]) == 1
            assert result["data"][0]["email_address"] == user_already_in_service.email_address

            # add new user to service
            user_to_add = User(
                name="Invited User",
                email_address="invited@digital.cabinet-office.gov.uk",
                password="password",
                mobile_number="+4477123456",
            )
            # they must exist in db first
            save_model_user(user_to_add)

            data = {
                "permissions": [
                    {"permission": "send_emails"},
                    {"permission": "send_letters"},
                    {"permission": "send_texts"},
                    {"permission": "manage_users"},
                    {"permission": "manage_settings"},
                    {"permission": "manage_api_keys"},
                    {"permission": "manage_templates"},
                    {"permission": "view_activity"},
                ],
                "folder_permissions": [],
            }

            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}/users/{}".format(sample_service.id, user_to_add.id),
                headers=[("Content-Type", "application/json"), auth_header],
                data=json.dumps(data),
            )

            assert resp.status_code == 201

            # check new user added to service
            auth_header = create_authorization_header()

            resp = client.get(
                "/service/{}".format(sample_service.id),
                headers=[("Content-Type", "application/json"), auth_header],
            )
            assert resp.status_code == 200
            json_resp = resp.json
            assert str(user_to_add.id) in json_resp["data"]["users"]

            # check user has all permissions
            auth_header = create_authorization_header()
            resp = client.get(
                url_for("user.get_user", user_id=user_to_add.id),
                headers=[("Content-Type", "application/json"), auth_header],
            )

            assert resp.status_code == 200
            json_resp = resp.json
            permissions = json_resp["data"]["permissions"][str(sample_service.id)]
            expected_permissions = [
                "send_texts",
                "send_emails",
                "send_letters",
                "manage_users",
                "manage_settings",
                "manage_templates",
                "manage_api_keys",
                "view_activity",
            ]
            assert sorted(expected_permissions) == sorted(permissions)


def test_add_existing_user_to_another_service_with_send_permissions(
    notify_api, notify_db, notify_db_session, sample_service, sample_user
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            # they must exist in db first
            user_to_add = User(
                name="Invited User",
                email_address="invited@digital.cabinet-office.gov.uk",
                password="password",
                mobile_number="+4477123456",
            )
            save_model_user(user_to_add)

            data = {
                "permissions": [
                    {"permission": "send_emails"},
                    {"permission": "send_letters"},
                    {"permission": "send_texts"},
                ],
                "folder_permissions": [],
            }

            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}/users/{}".format(sample_service.id, user_to_add.id),
                headers=[("Content-Type", "application/json"), auth_header],
                data=json.dumps(data),
            )

            assert resp.status_code == 201

            # check user has send permissions
            auth_header = create_authorization_header()
            resp = client.get(
                url_for("user.get_user", user_id=user_to_add.id),
                headers=[("Content-Type", "application/json"), auth_header],
            )

            assert resp.status_code == 200
            json_resp = resp.json

            permissions = json_resp["data"]["permissions"][str(sample_service.id)]
            expected_permissions = ["send_texts", "send_emails", "send_letters"]
            assert sorted(expected_permissions) == sorted(permissions)


def test_add_existing_user_to_another_service_with_manage_permissions(
    notify_api, notify_db, notify_db_session, sample_service, sample_user
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            # they must exist in db first
            user_to_add = User(
                name="Invited User",
                email_address="invited@digital.cabinet-office.gov.uk",
                password="password",
                mobile_number="+4477123456",
            )
            save_model_user(user_to_add)

            data = {
                "permissions": [
                    {"permission": "manage_users"},
                    {"permission": "manage_settings"},
                    {"permission": "manage_templates"},
                ]
            }

            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}/users/{}".format(sample_service.id, user_to_add.id),
                headers=[("Content-Type", "application/json"), auth_header],
                data=json.dumps(data),
            )

            assert resp.status_code == 201

            # check user has send permissions
            auth_header = create_authorization_header()
            resp = client.get(
                url_for("user.get_user", user_id=user_to_add.id),
                headers=[("Content-Type", "application/json"), auth_header],
            )

            assert resp.status_code == 200
            json_resp = resp.json

            permissions = json_resp["data"]["permissions"][str(sample_service.id)]
            expected_permissions = [
                "manage_users",
                "manage_settings",
                "manage_templates",
            ]
            assert sorted(expected_permissions) == sorted(permissions)


def test_add_existing_user_to_another_service_with_folder_permissions(
    notify_api, notify_db, notify_db_session, sample_service, sample_user
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            # they must exist in db first
            user_to_add = User(
                name="Invited User",
                email_address="invited@digital.cabinet-office.gov.uk",
                password="password",
                mobile_number="+4477123456",
            )
            save_model_user(user_to_add)

            folder_1 = create_template_folder(sample_service)
            folder_2 = create_template_folder(sample_service)

            data = {
                "permissions": [{"permission": "manage_api_keys"}],
                "folder_permissions": [str(folder_1.id), str(folder_2.id)],
            }

            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}/users/{}".format(sample_service.id, user_to_add.id),
                headers=[("Content-Type", "application/json"), auth_header],
                data=json.dumps(data),
            )

            assert resp.status_code == 201

            new_user = dao_get_service_user(user_id=user_to_add.id, service_id=sample_service.id)

            assert len(new_user.folders) == 2
            assert folder_1 in new_user.folders
            assert folder_2 in new_user.folders


def test_add_existing_user_to_another_service_with_manage_api_keys(
    notify_api, notify_db, notify_db_session, sample_service, sample_user
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            # they must exist in db first
            user_to_add = User(
                name="Invited User",
                email_address="invited@digital.cabinet-office.gov.uk",
                password="password",
                mobile_number="+4477123456",
            )
            save_model_user(user_to_add)

            data = {"permissions": [{"permission": "manage_api_keys"}]}

            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}/users/{}".format(sample_service.id, user_to_add.id),
                headers=[("Content-Type", "application/json"), auth_header],
                data=json.dumps(data),
            )

            assert resp.status_code == 201

            # check user has send permissions
            auth_header = create_authorization_header()
            resp = client.get(
                url_for("user.get_user", user_id=user_to_add.id),
                headers=[("Content-Type", "application/json"), auth_header],
            )

            assert resp.status_code == 200
            json_resp = resp.json

            permissions = json_resp["data"]["permissions"][str(sample_service.id)]
            expected_permissions = ["manage_api_keys"]
            assert sorted(expected_permissions) == sorted(permissions)


def test_add_existing_user_to_non_existing_service_returns404(notify_api, notify_db, notify_db_session, sample_user):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            user_to_add = User(
                name="Invited User",
                email_address="invited@digital.cabinet-office.gov.uk",
                password="password",
                mobile_number="+4477123456",
            )
            save_model_user(user_to_add)

            incorrect_id = uuid.uuid4()

            data = {"permissions": ["send_messages", "manage_service", "manage_api_keys"]}
            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}/users/{}".format(incorrect_id, user_to_add.id),
                headers=[("Content-Type", "application/json"), auth_header],
                data=json.dumps(data),
            )

            result = resp.json
            expected_message = "No result found"

            assert resp.status_code == 404
            assert result["result"] == "error"
            assert result["message"] == expected_message


def test_add_existing_user_of_service_to_service_returns409(notify_api, notify_db, notify_db_session, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            existing_user_id = sample_service.users[0].id

            data = {"permissions": ["send_messages", "manage_service", "manage_api_keys"]}
            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}/users/{}".format(sample_service.id, existing_user_id),
                headers=[("Content-Type", "application/json"), auth_header],
                data=json.dumps(data),
            )

            result = resp.json
            expected_message = "User id: {} already part of service id: {}".format(existing_user_id, sample_service.id)

            assert resp.status_code == 409
            assert result["result"] == "error"
            assert result["message"] == expected_message


def test_add_unknown_user_to_service_returns404(notify_api, notify_db, notify_db_session, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            incorrect_id = 9876

            data = {"permissions": ["send_messages", "manage_service", "manage_api_keys"]}
            auth_header = create_authorization_header()

            resp = client.post(
                "/service/{}/users/{}".format(sample_service.id, incorrect_id),
                headers=[("Content-Type", "application/json"), auth_header],
                data=json.dumps(data),
            )

            result = resp.json
            expected_message = "No result found"

            assert resp.status_code == 404
            assert result["result"] == "error"
            assert result["message"] == expected_message


def test_remove_user_from_service(notify_db, notify_db_session, client, sample_user_service_permission, mocker):
    mocked_salesforce_client = mocker.patch("app.service.rest.salesforce_client")
    third_user = create_user(email="new@digital.cabinet-office.gov.uk")
    fourth_user = create_user(email="new@cds-snc.ca")
    # Simulates successfully adding a user to the service
    third_permission = create_sample_user_service_permission(notify_db, notify_db_session, user=third_user)
    create_sample_user_service_permission(notify_db, notify_db_session, user=fourth_user)
    endpoint = url_for(
        "service.remove_user_from_service",
        service_id=str(third_permission.service.id),
        user_id=str(third_permission.user.id),
    )
    auth_header = create_authorization_header()
    resp = client.delete(endpoint, headers=[("Content-Type", "application/json"), auth_header])
    assert resp.status_code == 204
    mocked_salesforce_client.engagement_delete_contact_role.assert_called_with(third_permission.service, third_permission.user)


def test_remove_user_from_service_only_user_with_manage_perm(
    notify_api, notify_db, notify_db_session, client, sample_user_service_permission, mocker
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            manage_settings_user = sample_user_service_permission.user
            second_user = create_user(email="new2@cds-snc.ca")
            third_user = create_user(email="new3@cds-snc.ca")
            create_sample_user_service_permission(notify_db, notify_db_session, user=second_user, permission="view_activity")
            create_sample_user_service_permission(notify_db, notify_db_session, user=third_user, permission="view_activity")
            endpoint = url_for(
                "service.remove_user_from_service",
                service_id=str(sample_user_service_permission.service.id),
                user_id=str(manage_settings_user.id),
            )
            auth_header = create_authorization_header()
            resp = client.delete(endpoint, headers=[("Content-Type", "application/json"), auth_header])
            assert resp.status_code == 400
            result = resp.json
            assert result["message"] == "SERVICE_NEEDS_USER_W_MANAGE_SETTINGS_PERM"


def test_remove_non_existant_user_from_service(client, sample_user_service_permission):
    second_user = create_user(email="new@digital.cabinet-office.gov.uk")
    endpoint = url_for(
        "service.remove_user_from_service",
        service_id=str(sample_user_service_permission.service.id),
        user_id=str(second_user.id),
    )
    auth_header = create_authorization_header()
    resp = client.delete(endpoint, headers=[("Content-Type", "application/json"), auth_header])
    assert resp.status_code == 404


def test_cannot_remove_only_user_from_service(notify_api, notify_db, notify_db_session, sample_user_service_permission):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            endpoint = url_for(
                "service.remove_user_from_service",
                service_id=str(sample_user_service_permission.service.id),
                user_id=str(sample_user_service_permission.user.id),
            )
            auth_header = create_authorization_header()
            resp = client.delete(endpoint, headers=[("Content-Type", "application/json"), auth_header])
            assert resp.status_code == 400
            result = resp.json
            assert result["message"] == "You cannot remove the only user for a service"


def test_remove_user_from_service_with_2_users(
    notify_api, notify_db, notify_db_session, client, sample_user_service_permission, mocker
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            second_user = create_user(email="new@cds-snc.ca")
            create_sample_user_service_permission(notify_db, notify_db_session, user=second_user, permission="view_activity")
            endpoint = url_for(
                "service.remove_user_from_service",
                service_id=str(sample_user_service_permission.service.id),
                user_id=str(sample_user_service_permission.user.id),
            )
            auth_header = create_authorization_header()
            resp = client.delete(endpoint, headers=[("Content-Type", "application/json"), auth_header])
            assert resp.status_code == 400
            result = resp.json
            assert result["message"] == "SERVICE_CANNOT_HAVE_LT_2_MEMBERS"


# This test is just here verify get_service_and_api_key_history that is a temp solution
# until proper ui is sorted out on admin app
def test_get_service_and_api_key_history(notify_api, notify_db, notify_db_session, sample_service):
    from tests.app.conftest import create_sample_api_key

    api_key = create_sample_api_key(notify_db, notify_db_session, service=sample_service)

    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            auth_header = create_authorization_header()
            response = client.get(
                path="/service/{}/history".format(sample_service.id),
                headers=[auth_header],
            )
            assert response.status_code == 200

            json_resp = json.loads(response.get_data(as_text=True))
            assert json_resp["data"]["service_history"][0]["id"] == str(sample_service.id)
            assert json_resp["data"]["api_key_history"][0]["id"] == str(api_key.id)


def test_get_all_notifications_for_service_in_order(notify_api, notify_db, notify_db_session):
    with notify_api.test_request_context(), notify_api.test_client() as client:
        service_1 = create_service(service_name="1", email_from="1")
        service_2 = create_service(service_name="2", email_from="2")

        create_sample_notification(notify_db, notify_db_session, service=service_2)

        notification_1 = create_sample_notification(notify_db, notify_db_session, service=service_1)
        notification_2 = create_sample_notification(notify_db, notify_db_session, service=service_1)
        notification_3 = create_sample_notification(notify_db, notify_db_session, service=service_1)

        auth_header = create_authorization_header()

        response = client.get(path="/service/{}/notifications".format(service_1.id), headers=[auth_header])

        resp = json.loads(response.get_data(as_text=True))
        assert len(resp["notifications"]) == 3
        assert resp["notifications"][0]["to"] == notification_3.to
        assert resp["notifications"][1]["to"] == notification_2.to
        assert resp["notifications"][2]["to"] == notification_1.to
        assert response.status_code == 200


def test_get_all_notifications_for_service_formatted_for_csv(client, sample_template):
    notification = save_notification(create_notification(template=sample_template))
    auth_header = create_authorization_header()

    response = client.get(
        path="/service/{}/notifications?format_for_csv=True".format(sample_template.service_id),
        headers=[auth_header],
    )

    resp = json.loads(response.get_data(as_text=True))
    assert response.status_code == 200
    assert len(resp["notifications"]) == 1
    assert resp["notifications"][0]["recipient"] == notification.to
    assert not resp["notifications"][0]["row_number"]
    assert resp["notifications"][0]["template_name"] == sample_template.name
    assert resp["notifications"][0]["template_type"] == notification.notification_type
    assert resp["notifications"][0]["status"] == "In transit"


def test_get_notification_for_service_without_uuid(client, notify_db, notify_db_session):
    service_1 = create_service(service_name="1", email_from="1")
    response = client.get(
        path="/service/{}/notifications/{}".format(service_1.id, "foo"),
        headers=[create_authorization_header()],
    )
    assert response.status_code == 404


def test_get_notification_for_service(client, notify_db, notify_db_session):
    service_1 = create_service(service_name="1", email_from="1")
    service_2 = create_service(service_name="2", email_from="2")

    service_1_notifications = [
        create_sample_notification(notify_db, notify_db_session, service=service_1),
        create_sample_notification(notify_db, notify_db_session, service=service_1),
        create_sample_notification(notify_db, notify_db_session, service=service_1),
    ]

    create_sample_notification(notify_db, notify_db_session, service=service_2)

    for notification in service_1_notifications:
        response = client.get(
            path="/service/{}/notifications/{}".format(service_1.id, notification.id),
            headers=[create_authorization_header()],
        )
        resp = json.loads(response.get_data(as_text=True))
        assert str(resp["id"]) == str(notification.id)
        assert response.status_code == 200

        service_2_response = client.get(
            path="/service/{}/notifications/{}".format(service_2.id, notification.id),
            headers=[create_authorization_header()],
        )
        assert service_2_response.status_code == 404
        service_2_response = json.loads(service_2_response.get_data(as_text=True))
        assert service_2_response == {"message": "Notification not found in database", "result": "error"}


def test_get_notification_for_service_includes_created_by(admin_request, sample_notification):
    user = sample_notification.created_by = sample_notification.service.created_by

    resp = admin_request.get(
        "service.get_notification_for_service",
        service_id=sample_notification.service_id,
        notification_id=sample_notification.id,
    )

    assert resp["id"] == str(sample_notification.id)
    assert resp["created_by"] == {
        "id": str(user.id),
        "name": user.name,
        "email_address": user.email_address,
    }


def test_get_notification_for_service_returns_old_template_version(admin_request, sample_template):
    sample_notification = save_notification(create_notification(sample_template))
    sample_notification.reference = "modified-inplace"
    sample_template.version = 2
    sample_template.content = "New template content"

    resp = admin_request.get(
        "service.get_notification_for_service",
        service_id=sample_notification.service_id,
        notification_id=sample_notification.id,
    )

    assert resp["reference"] == "modified-inplace"
    assert resp["template"]["version"] == 1
    assert resp["template"]["content"] == sample_notification.template.content
    assert resp["template"]["content"] != sample_template.content


@pytest.mark.parametrize("include_from_test_key, expected_count_of_notifications", [(False, 2), (True, 3)])
def test_get_all_notifications_for_service_including_ones_made_by_jobs(
    client,
    notify_db,
    notify_db_session,
    sample_service,
    include_from_test_key,
    expected_count_of_notifications,
):
    with_job = create_sample_notification_with_job(notify_db, notify_db_session, service=sample_service)
    without_job = create_sample_notification(notify_db, notify_db_session, service=sample_service)
    # from_test_api_key
    create_sample_notification(notify_db, notify_db_session, service=sample_service, key_type=KEY_TYPE_TEST)

    auth_header = create_authorization_header()

    response = client.get(
        path="/service/{}/notifications?include_from_test_key={}".format(sample_service.id, include_from_test_key),
        headers=[auth_header],
    )

    resp = json.loads(response.get_data(as_text=True))
    assert len(resp["notifications"]) == expected_count_of_notifications
    assert resp["notifications"][0]["to"] == with_job.to
    assert resp["notifications"][1]["to"] == without_job.to
    assert response.status_code == 200


def test_get_only_api_created_notifications_for_service(
    admin_request,
    sample_job,
    sample_template,
    sample_user,
):
    # notification sent as a job
    save_notification(create_notification(sample_template, job=sample_job))
    # notification sent as a one-off
    save_notification(create_notification(sample_template, one_off=True, created_by_id=sample_user.id))
    # notification sent via API
    without_job = save_notification(create_notification(sample_template))

    resp = admin_request.get(
        "service.get_all_notifications_for_service",
        service_id=sample_template.service_id,
        include_jobs=False,
        include_one_off=False,
    )
    assert len(resp["notifications"]) == 1
    assert resp["notifications"][0]["id"] == str(without_job.id)


def test_get_notifications_for_service_without_page_count(
    admin_request,
    sample_job,
    sample_template,
    sample_user,
):
    save_notification(create_notification(sample_template))
    without_job = save_notification(create_notification(sample_template))

    resp = admin_request.get(
        "service.get_all_notifications_for_service",
        service_id=sample_template.service_id,
        page_size=1,
        include_jobs=False,
        include_one_off=False,
        count_pages=False,
    )
    assert len(resp["notifications"]) == 1
    assert resp["total"] is None
    assert resp["notifications"][0]["id"] == str(without_job.id)


@freeze_time("2018-11-20T18:00:00")
@pytest.mark.parametrize("retention_period, expected_count_of_notifications", [(3, 72), (7, 168)])
def test_get_notifications_for_service_gets_data_from_correct_timeframe(
    admin_request, sample_service, retention_period, expected_count_of_notifications
):
    email_template = create_template(service=sample_service, template_type=EMAIL_TYPE)

    # WEEK BEFORE
    # Create 12 notifications for each hour of the day for 1 week
    for i in range(retention_period):
        for j in range(24):
            save_notification(
                create_notification(email_template, created_at=datetime(2018, 11, 5 + i, j, 0, 0), status="delivered")
            )

    # THIS WEEK
    # Create 12 notifications for each hour of the day for 1 week
    for i in range(retention_period):
        for j in range(24):
            save_notification(
                create_notification(email_template, created_at=datetime(2018, 11, 14 + i, j, 0, 0), status="delivered")
            )

    resp = admin_request.get(
        "service.get_all_notifications_for_service", service_id=email_template.service_id, limit_days=7, page_size=1
    )
    assert resp["total"] == expected_count_of_notifications  #


@pytest.mark.parametrize(
    "should_prefix",
    [
        True,
        False,
    ],
)
def test_prefixing_messages_based_on_prefix_sms(
    client,
    notify_db_session,
    should_prefix,
):
    service = create_service(prefix_sms=should_prefix)

    result = client.get(
        url_for("service.get_service_by_id", service_id=service.id),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    service = json.loads(result.get_data(as_text=True))["data"]
    assert service["prefix_sms"] == should_prefix


@pytest.mark.parametrize(
    "posted_value, stored_value, returned_value",
    [
        (True, True, True),
        (False, False, False),
    ],
)
def test_set_sms_prefixing_for_service(
    admin_request,
    client,
    sample_service,
    posted_value,
    stored_value,
    returned_value,
):
    result = admin_request.post(
        "service.update_service",
        service_id=sample_service.id,
        _data={"prefix_sms": posted_value},
    )
    assert result["data"]["prefix_sms"] == stored_value


def test_set_sms_prefixing_for_service_cant_be_none(
    admin_request,
    sample_service,
):
    resp = admin_request.post(
        "service.update_service",
        service_id=sample_service.id,
        _data={"prefix_sms": None},
        _expected_status=400,
    )
    assert resp["message"] == {"prefix_sms": ["Field may not be null."]}


@pytest.mark.parametrize(
    "today_only,stats",
    [
        ("False", {"requested": 2, "delivered": 1, "failed": 0}),
        ("True", {"requested": 1, "delivered": 0, "failed": 0}),
    ],
    ids=["seven_days", "today"],
)
def test_get_detailed_service(notify_db, notify_db_session, notify_api, sample_service, today_only, stats):
    with notify_api.test_request_context(), notify_api.test_client() as client:
        create_ft_notification_status(date(2000, 1, 1), "sms", sample_service, count=1)
        with freeze_time("2000-01-02T12:00:00"):
            create_sample_notification(notify_db, notify_db_session, status="created")
            resp = client.get(
                "/service/{}?detailed=True&today_only={}".format(sample_service.id, today_only),
                headers=[create_authorization_header()],
            )

    assert resp.status_code == 200
    service = resp.json["data"]
    assert service["id"] == str(sample_service.id)
    assert "statistics" in service.keys()
    assert set(service["statistics"].keys()) == {SMS_TYPE, EMAIL_TYPE, LETTER_TYPE}
    assert service["statistics"][SMS_TYPE] == stats


def test_get_services_with_detailed_flag(client, notify_db, notify_db_session):
    notifications = [
        create_sample_notification(notify_db, notify_db_session),
        create_sample_notification(notify_db, notify_db_session),
        create_sample_notification(notify_db, notify_db_session, key_type=KEY_TYPE_TEST),
    ]
    resp = client.get("/service?detailed=True", headers=[create_authorization_header()])

    assert resp.status_code == 200
    data = resp.json["data"]
    assert len(data) == 1
    assert data[0]["name"] == "Sample service"
    assert data[0]["id"] == str(notifications[0].service_id)
    assert data[0]["statistics"] == {
        EMAIL_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
        SMS_TYPE: {"delivered": 0, "failed": 0, "requested": 3},
        LETTER_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
    }


def test_get_services_with_detailed_flag_excluding_from_test_key(notify_api, notify_db, notify_db_session):
    (create_sample_notification(notify_db, notify_db_session, key_type=KEY_TYPE_NORMAL),)
    (create_sample_notification(notify_db, notify_db_session, key_type=KEY_TYPE_TEAM),)
    (create_sample_notification(notify_db, notify_db_session, key_type=KEY_TYPE_TEST),)
    (create_sample_notification(notify_db, notify_db_session, key_type=KEY_TYPE_TEST),)
    create_sample_notification(notify_db, notify_db_session, key_type=KEY_TYPE_TEST)

    with notify_api.test_request_context(), notify_api.test_client() as client:
        resp = client.get(
            "/service?detailed=True&include_from_test_key=False",
            headers=[create_authorization_header()],
        )

    assert resp.status_code == 200
    data = resp.json["data"]
    assert len(data) == 1
    assert data[0]["statistics"] == {
        EMAIL_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
        SMS_TYPE: {"delivered": 0, "failed": 0, "requested": 2},
        LETTER_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
    }


def test_get_services_with_detailed_flag_accepts_date_range(client, mocker):
    mock_get_detailed_services = mocker.patch("app.service.rest.get_detailed_services", return_value={})
    resp = client.get(
        url_for(
            "service.get_services",
            detailed=True,
            start_date="2001-01-01",
            end_date="2002-02-02",
        ),
        headers=[create_authorization_header()],
    )

    mock_get_detailed_services.assert_called_once_with(
        start_date=date(2001, 1, 1),
        end_date=date(2002, 2, 2),
        only_active=ANY,
        include_from_test_key=ANY,
    )
    assert resp.status_code == 200


@freeze_time("2002-02-02")
def test_get_services_with_detailed_flag_defaults_to_today(client, mocker):
    mock_get_detailed_services = mocker.patch("app.service.rest.get_detailed_services", return_value={})
    resp = client.get(
        url_for("service.get_services", detailed=True),
        headers=[create_authorization_header()],
    )

    mock_get_detailed_services.assert_called_once_with(
        end_date=date(2002, 2, 2),
        include_from_test_key=ANY,
        only_active=ANY,
        start_date=date(2002, 2, 2),
    )

    assert resp.status_code == 200


def test_get_detailed_services_groups_by_service(notify_db, notify_db_session):
    from app.service.rest import get_detailed_services

    service_1 = create_service(service_name="1", email_from="1")
    service_2 = create_service(service_name="2", email_from="2")

    create_sample_notification(notify_db, notify_db_session, service=service_1, status="created")
    create_sample_notification(notify_db, notify_db_session, service=service_2, status="created")
    create_sample_notification(notify_db, notify_db_session, service=service_1, status="delivered")
    create_sample_notification(notify_db, notify_db_session, service=service_1, status="created")

    data = get_detailed_services(start_date=datetime.utcnow().date(), end_date=datetime.utcnow().date())
    data = sorted(data, key=lambda x: x["name"])

    assert len(data) == 2
    assert data[0]["id"] == str(service_1.id)
    assert data[0]["statistics"] == {
        EMAIL_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
        SMS_TYPE: {"delivered": 1, "failed": 0, "requested": 3},
        LETTER_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
    }
    assert data[1]["id"] == str(service_2.id)
    assert data[1]["statistics"] == {
        EMAIL_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
        SMS_TYPE: {"delivered": 0, "failed": 0, "requested": 1},
        LETTER_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
    }


def test_get_detailed_services_includes_services_with_no_notifications(notify_db, notify_db_session):
    from app.service.rest import get_detailed_services

    service_1 = create_service(service_name="1", email_from="1")
    service_2 = create_service(service_name="2", email_from="2")

    create_sample_notification(notify_db, notify_db_session, service=service_1)

    data = get_detailed_services(start_date=datetime.utcnow().date(), end_date=datetime.utcnow().date())
    data = sorted(data, key=lambda x: x["name"])

    assert len(data) == 2
    assert data[0]["id"] == str(service_1.id)
    assert data[0]["statistics"] == {
        EMAIL_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
        SMS_TYPE: {"delivered": 0, "failed": 0, "requested": 1},
        LETTER_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
    }
    assert data[1]["id"] == str(service_2.id)
    assert data[1]["statistics"] == {
        EMAIL_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
        SMS_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
        LETTER_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
    }


# This test assumes the local timezone is EST
def test_get_detailed_services_only_includes_todays_notifications(notify_db, notify_db_session):
    from app.service.rest import get_detailed_services

    create_sample_notification(notify_db, notify_db_session, created_at=datetime(2015, 10, 10, 3, 59))
    create_sample_notification(notify_db, notify_db_session, created_at=datetime(2015, 10, 10, 4, 0))
    create_sample_notification(notify_db, notify_db_session, created_at=datetime(2015, 10, 10, 12, 0))
    create_sample_notification(notify_db, notify_db_session, created_at=datetime(2015, 10, 11, 3, 0))

    with freeze_time("2015-10-10T12:00:00"):
        data = get_detailed_services(start_date=datetime.utcnow().date(), end_date=datetime.utcnow().date())
        data = sorted(data, key=lambda x: x["id"])

    assert len(data) == 1
    assert data[0]["statistics"] == {
        EMAIL_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
        SMS_TYPE: {"delivered": 0, "failed": 0, "requested": 3},
        LETTER_TYPE: {"delivered": 0, "failed": 0, "requested": 0},
    }


@pytest.mark.parametrize("start_date_delta, end_date_delta", [(2, 1), (3, 2), (1, 0)])
@freeze_time("2017-03-28T12:00:00")
def test_get_detailed_services_for_date_range(sample_template, start_date_delta, end_date_delta):
    from app.service.rest import get_detailed_services

    create_ft_notification_status(
        utc_date=(datetime.utcnow() - timedelta(days=3)).date(),
        service=sample_template.service,
        notification_type="sms",
    )
    create_ft_notification_status(
        utc_date=(datetime.utcnow() - timedelta(days=2)).date(),
        service=sample_template.service,
        notification_type="sms",
    )
    create_ft_notification_status(
        utc_date=(datetime.utcnow() - timedelta(days=1)).date(),
        service=sample_template.service,
        notification_type="sms",
    )

    save_notification(create_notification(template=sample_template, created_at=datetime.utcnow(), status="delivered"))

    start_date = (datetime.utcnow() - timedelta(days=start_date_delta)).date()
    end_date = (datetime.utcnow() - timedelta(days=end_date_delta)).date()

    data = get_detailed_services(
        only_active=False,
        include_from_test_key=True,
        start_date=start_date,
        end_date=end_date,
    )

    assert len(data) == 1
    assert data[0]["statistics"][EMAIL_TYPE] == {
        "delivered": 0,
        "failed": 0,
        "requested": 0,
    }
    assert data[0]["statistics"][SMS_TYPE] == {
        "delivered": 2,
        "failed": 0,
        "requested": 2,
    }
    assert data[0]["statistics"][LETTER_TYPE] == {
        "delivered": 0,
        "failed": 0,
        "requested": 0,
    }


def test_search_for_notification_by_to_field(client, sample_template, sample_email_template):
    notification1 = save_notification(
        create_notification(template=sample_template, to_field="+16502532222", normalised_to="+16502532222")
    )
    notification2 = save_notification(
        create_notification(
            template=sample_email_template,
            to_field="jack@gmail.com",
            normalised_to="jack@gmail.com",
        )
    )

    response = client.get(
        "/service/{}/notifications?to={}&template_type={}".format(notification1.service_id, "jack@gmail.com", "email"),
        headers=[create_authorization_header()],
    )
    notifications = json.loads(response.get_data(as_text=True))["notifications"]

    assert response.status_code == 200
    assert len(notifications) == 1
    assert str(notification2.id) == notifications[0]["id"]


def test_search_for_notification_by_to_field_return_empty_list_if_there_is_no_match(client, notify_db, notify_db_session):
    create_notification = partial(create_sample_notification, notify_db, notify_db_session)
    notification1 = save_notification(create_notification(to_field="+16502532222"))
    save_notification(create_notification(to_field="jack@gmail.com"))

    response = client.get(
        "/service/{}/notifications?to={}&template_type={}".format(notification1.service_id, "+447700900800", "sms"),
        headers=[create_authorization_header()],
    )
    notifications = json.loads(response.get_data(as_text=True))["notifications"]

    assert response.status_code == 200
    assert len(notifications) == 0


def test_search_for_notification_by_to_field_return_multiple_matches(client, notify_db, notify_db_session):
    create_notification = partial(create_sample_notification, notify_db, notify_db_session)
    notification1 = save_notification(create_notification(to_field="+16502532222", normalised_to="+16502532222"))
    notification2 = save_notification(create_notification(to_field=" +165 0253 2222 ", normalised_to="+16502532222"))
    notification3 = save_notification(create_notification(to_field="+1 650 253 2222", normalised_to="+16502532222"))
    notification4 = save_notification(create_notification(to_field="jack@gmail.com", normalised_to="jack@gmail.com"))

    response = client.get(
        "/service/{}/notifications?to={}&template_type={}".format(notification1.service_id, "+16502532222", "sms"),
        headers=[create_authorization_header()],
    )
    notifications = json.loads(response.get_data(as_text=True))["notifications"]
    notification_ids = [notification["id"] for notification in notifications]

    assert response.status_code == 200
    assert len(notifications) == 3

    assert str(notification1.id) in notification_ids
    assert str(notification2.id) in notification_ids
    assert str(notification3.id) in notification_ids
    assert str(notification4.id) not in notification_ids


def test_search_for_notification_by_to_field_return_400_for_letter_type(client, notify_db, notify_db_session, sample_service):
    response = client.get(
        "/service/{}/notifications?to={}&template_type={}".format(sample_service.id, "A. Name", "letter"),
        headers=[create_authorization_header()],
    )
    response.status_code = 400
    error_message = json.loads(response.get_data(as_text=True))
    assert error_message["message"] == "Only email and SMS can use search by recipient"


@pytest.mark.parametrize("set_go_live_user", [True, False])
def test_update_service_calls_send_notification_as_service_becomes_live(
    notify_db: RoutingSQLAlchemy,
    notify_db_session: RoutingSQLAlchemy,
    client: Flask,
    mocker: pytest_mock.MockFixture,
    set_go_live_user: bool,
):
    user_1 = create_user(email="active1@foo.com", state="active")
    user_2 = create_user(email="active2@foo.com", state="active") if set_go_live_user else None

    send_notification_mock = mocker.patch("app.service.rest.send_notification_to_service_users")
    restricted_service = create_service(user=user_1, go_live_user=user_2, restricted=True)

    data = {"restricted": False}

    mocked_salesforce_client = mocker.patch("app.service.rest.salesforce_client")
    mocked_fetch_service_creator = mocker.patch("app.service.rest.dao_fetch_service_creator", return_value=user_1)
    mocked_get_user_by_id = mocker.patch("app.service.rest.get_user_by_id", return_value=user_2)

    auth_header = create_authorization_header()
    resp = client.post(
        "service/{}".format(restricted_service.id),
        data=json.dumps(data),
        headers=[auth_header],
        content_type="application/json",
    )

    assert resp.status_code == 200  # type: ignore
    send_notification_mock.assert_called_once_with(
        service_id=restricted_service.id,
        template_id="618185c6-3636-49cd-b7d2-6f6f5eb3bdde",
        personalisation={
            "service_name": restricted_service.name,
            "contact_us_url": f"{current_app.config['ADMIN_BASE_URL']}/contact",
            "signin_url": f"{current_app.config['ADMIN_BASE_URL']}/sign-in",
            "message_limit_en": "1,000",
            "message_limit_fr": "1 000",
        },
        include_user_fields=["name"],
    )

    engagement_user = user_2 if set_go_live_user else user_1
    mocked_salesforce_client.engagement_update.assert_called_once_with(
        restricted_service, engagement_user, {"StageName": ENGAGEMENT_STAGE_LIVE}
    )
    if set_go_live_user:
        mocked_fetch_service_creator.assert_not_called()
        mocked_get_user_by_id.assert_called_once_with(restricted_service.go_live_user_id)
    else:
        mocked_fetch_service_creator.assert_called_once_with(restricted_service.id)
        mocked_get_user_by_id.assert_not_called()


@pytest.mark.parametrize(
    "current_limit, new_limit, expected_call",
    [
        (1_000, 1_000, False),
        (1_000, 2_000, True),
        (1_000, 50, True),
        (1_000, None, False),
    ],
)
def test_update_service_updating_daily_limit_clears_redis_cache(
    notify_db,
    notify_db_session,
    admin_request,
    mocker,
    current_limit,
    new_limit,
    expected_call,
):
    redis_delete = mocker.patch("app.service.rest.redis_store.delete")
    mocker.patch("app.service.rest.send_notification_to_service_users")

    service = create_service(message_limit=current_limit)

    admin_request.post(
        "service.update_service",
        service_id=service.id,
        _data={"message_limit": new_limit} if new_limit else {},
        _expected_status=200,
    )

    if expected_call:
        redis_delete.call_args_list == [
            call(daily_limit_cache_key(service.id)),
            call(near_daily_limit_cache_key(service.id)),
            call(over_daily_limit_cache_key(service.id)),
            call(near_email_daily_limit_cache_key(service.id)),
            call(over_email_daily_limit_cache_key(service.id)),
        ]
    else:
        redis_delete.assert_not_called()


@pytest.mark.parametrize(
    "is_trial, current_limit, new_limit, expected_call",
    [
        (False, 1_000, 1_000, False),
        (False, 1_000, 2_000, True),
        (True, 50, 2_000, False),
        (False, 1_000, 50, True),
        (False, 1_000, None, False),
        (True, 1_000, None, False),
    ],
)
def test_update_service_updating_daily_limit_sends_notification_to_users(
    notify_db,
    notify_db_session,
    admin_request,
    mocker,
    is_trial,
    current_limit,
    new_limit,
    expected_call,
):
    send_notification_mock = mocker.patch("app.service.rest.send_notification_to_service_users")

    service = create_service(message_limit=current_limit, restricted=is_trial)

    admin_request.post(
        "service.update_service",
        service_id=service.id,
        _data={"message_limit": new_limit} if new_limit else {},
        _expected_status=200,
    )

    if expected_call:
        send_notification_mock.assert_called_once_with(
            service_id=service.id,
            template_id=current_app.config["DAILY_EMAIL_LIMIT_UPDATED_TEMPLATE_ID"],
            personalisation={
                "service_name": service.name,
                "message_limit_en": "{:,}".format(new_limit),
                "message_limit_fr": "{:,}".format(new_limit).replace(",", " "),
            },
            include_user_fields=["name"],
        )
    else:
        send_notification_mock.assert_not_called()


def test_update_service_does_not_call_send_notification_for_live_service(sample_service, client, mocker):
    send_notification_mock = mocker.patch("app.service.rest.send_notification_to_service_users")

    data = {"restricted": True}

    auth_header = create_authorization_header()
    resp = client.post(
        "service/{}".format(sample_service.id),
        data=json.dumps(data),
        headers=[auth_header],
        content_type="application/json",
    )

    assert resp.status_code == 200
    assert not send_notification_mock.called


def test_update_service_does_not_call_send_notification_when_restricted_not_changed(sample_service, client, mocker):
    send_notification_mock = mocker.patch("app.service.rest.send_notification_to_service_users")

    data = {"name": "Name of service"}

    auth_header = create_authorization_header()
    resp = client.post(
        "service/{}".format(sample_service.id),
        data=json.dumps(data),
        headers=[auth_header],
        content_type="application/json",
    )

    assert resp.status_code == 200
    assert not send_notification_mock.called


def test_update_service_name_updates_salesforce_engagement(sample_service, client, mocker):
    user = create_user(email="active1@foo.com", state="active")
    mocked_salesforce_client = mocker.patch("app.service.rest.salesforce_client")
    mocker.patch("app.service.rest.dao_fetch_service_creator", return_value=user)

    data = {"name": "New service name"}

    auth_header = create_authorization_header()
    resp = client.post(
        "service/{}".format(sample_service.id),
        data=json.dumps(data),
        headers=[auth_header],
        content_type="application/json",
    )
    assert resp.status_code == 200
    mocked_salesforce_client.engagement_update.assert_called_once_with(sample_service, user, {"Name": "New service name"})


def test_search_for_notification_by_to_field_filters_by_status(client, notify_db, notify_db_session):
    create_notification = partial(
        create_sample_notification,
        notify_db,
        notify_db_session,
        to_field="+16502532222",
        normalised_to="+16502532222",
    )
    notification1 = save_notification(create_notification(status="delivered"))
    save_notification(create_notification(status="sending"))

    response = client.get(
        "/service/{}/notifications?to={}&status={}&template_type={}".format(
            notification1.service_id, "+16502532222", "delivered", "sms"
        ),
        headers=[create_authorization_header()],
    )
    notifications = json.loads(response.get_data(as_text=True))["notifications"]
    notification_ids = [notification["id"] for notification in notifications]

    assert response.status_code == 200
    assert len(notifications) == 1
    assert str(notification1.id) in notification_ids


def test_search_for_notification_by_to_field_filters_by_statuses(client, notify_db, notify_db_session):
    create_notification = partial(
        create_sample_notification,
        notify_db,
        notify_db_session,
        to_field="+16502532222",
        normalised_to="+16502532222",
    )
    notification1 = save_notification(create_notification(status="delivered"))
    notification2 = save_notification(create_notification(status="sending"))

    response = client.get(
        "/service/{}/notifications?to={}&status={}&status={}&template_type={}".format(
            notification1.service_id, "+16502532222", "delivered", "sending", "sms"
        ),
        headers=[create_authorization_header()],
    )
    notifications = json.loads(response.get_data(as_text=True))["notifications"]
    notification_ids = [notification["id"] for notification in notifications]

    assert response.status_code == 200
    assert len(notifications) == 2
    assert str(notification1.id) in notification_ids
    assert str(notification2.id) in notification_ids


def test_search_for_notification_by_to_field_returns_content(
    client, notify_db, notify_db_session, sample_template_with_placeholders
):
    notification = create_sample_notification(
        notify_db,
        notify_db_session,
        to_field="+16502532222",
        normalised_to="+16502532222",
        template=sample_template_with_placeholders,
        personalisation={"name": "Foo"},
    )

    response = client.get(
        "/service/{}/notifications?to={}&template_type={}".format(
            sample_template_with_placeholders.service_id, "+16502532222", "sms"
        ),
        headers=[create_authorization_header()],
    )
    notifications = json.loads(response.get_data(as_text=True))["notifications"]
    assert response.status_code == 200
    assert len(notifications) == 1

    assert notifications[0]["id"] == str(notification.id)
    assert notifications[0]["to"] == "+16502532222"
    assert notifications[0]["template"]["content"] == "Hello (( Name))\nYour thing is due soon"


def test_send_one_off_notification(sample_service, admin_request, mocker):
    template = create_template(service=sample_service)
    mocker.patch("app.service.send_notification.send_notification_to_queue")

    response = admin_request.post(
        "service.create_one_off_notification",
        service_id=sample_service.id,
        _data={
            "template_id": str(template.id),
            "to": "+16502532222",
            "created_by": str(sample_service.created_by_id),
        },
        _expected_status=201,
    )

    noti = Notification.query.one()
    assert response["id"] == str(noti.id)


def test_get_notification_for_service_includes_template_redacted(admin_request, sample_notification):
    resp = admin_request.get(
        "service.get_notification_for_service",
        service_id=sample_notification.service_id,
        notification_id=sample_notification.id,
    )

    assert resp["id"] == str(sample_notification.id)
    assert resp["template"]["redact_personalisation"] is False


def test_get_notification_for_service_includes_precompiled_letter(admin_request, sample_notification):
    resp = admin_request.get(
        "service.get_notification_for_service",
        service_id=sample_notification.service_id,
        notification_id=sample_notification.id,
    )

    assert resp["id"] == str(sample_notification.id)
    assert resp["template"]["is_precompiled_letter"] is False


def test_get_all_notifications_for_service_includes_template_redacted(admin_request, sample_service):
    normal_template = create_template(sample_service)

    redacted_template = create_template(sample_service)
    dao_redact_template(redacted_template, sample_service.created_by_id)

    with freeze_time("2000-01-01"):
        redacted_noti = save_notification(create_notification(redacted_template))
    with freeze_time("2000-01-02"):
        normal_noti = save_notification(create_notification(normal_template))

    resp = admin_request.get("service.get_all_notifications_for_service", service_id=sample_service.id)

    assert resp["notifications"][0]["id"] == str(normal_noti.id)
    assert resp["notifications"][0]["template"]["redact_personalisation"] is False

    assert resp["notifications"][1]["id"] == str(redacted_noti.id)
    assert resp["notifications"][1]["template"]["redact_personalisation"] is True


def test_get_all_notifications_for_service_includes_template_hidden(admin_request, sample_service):
    letter_template = create_template(sample_service, template_type=LETTER_TYPE)
    precompiled_template = create_template(
        sample_service,
        template_type=LETTER_TYPE,
        template_name="Pre-compiled PDF",
        subject="Pre-compiled PDF",
        hidden=True,
    )

    with freeze_time("2000-01-01"):
        letter_noti = save_notification(create_notification(letter_template))
    with freeze_time("2000-01-02"):
        precompiled_noti = save_notification(create_notification(precompiled_template))

    resp = admin_request.get("service.get_all_notifications_for_service", service_id=sample_service.id)

    assert resp["notifications"][0]["id"] == str(precompiled_noti.id)
    assert resp["notifications"][0]["template"]["is_precompiled_letter"] is True

    assert resp["notifications"][1]["id"] == str(letter_noti.id)
    assert resp["notifications"][1]["template"]["is_precompiled_letter"] is False


def test_search_for_notification_by_to_field_returns_personlisation(
    client, notify_db, notify_db_session, sample_template_with_placeholders
):
    create_sample_notification(
        notify_db,
        notify_db_session,
        to_field="+16502532222",
        normalised_to="+16502532222",
        template=sample_template_with_placeholders,
        personalisation={"name": "Foo"},
    )

    response = client.get(
        "/service/{}/notifications?to={}&template_type={}".format(
            sample_template_with_placeholders.service_id, "+16502532222", "sms"
        ),
        headers=[create_authorization_header()],
    )
    notifications = json.loads(response.get_data(as_text=True))["notifications"]

    assert response.status_code == 200
    assert len(notifications) == 1
    assert "personalisation" in notifications[0].keys()
    assert notifications[0]["personalisation"]["name"] == "Foo"


def test_search_for_notification_by_to_field_returns_notifications_by_type(
    client, notify_db, notify_db_session, sample_template, sample_email_template
):
    sms_notification = create_sample_notification(
        notify_db,
        notify_db_session,
        to_field="+16502532222",
        normalised_to="+16502532222",
        template=sample_template,
    )
    create_sample_notification(
        notify_db,
        notify_db_session,
        to_field="44770@gamil.com",
        normalised_to="44770@gamil.com",
        template=sample_email_template,
    )

    response = client.get(
        "/service/{}/notifications?to={}&template_type={}".format(sms_notification.service_id, "650", "sms"),
        headers=[create_authorization_header()],
    )
    notifications = json.loads(response.get_data(as_text=True))["notifications"]

    assert response.status_code == 200
    assert len(notifications) == 1
    assert notifications[0]["id"] == str(sms_notification.id)


def test_is_service_name_unique_returns_200_if_unique(admin_request, notify_db, notify_db_session):
    service = create_service(service_name="unique", email_from="unique")

    response = admin_request.get(
        "service.is_service_name_unique",
        _expected_status=200,
        name="something",
        service_id=service.id,
    )

    assert response == {"result": True}


def test_is_email_from_unique_returns_200_if_unique(admin_request, notify_db, notify_db_session):
    service = create_service(service_name="unique", email_from="unique")

    response = admin_request.get(
        "service.is_service_email_from_unique",
        _expected_status=200,
        service_id=service.id,
        email_from="something",
    )

    assert response == {"result": True}


@pytest.mark.parametrize("name", [("Unique."), ("**uniQUE**")])
def test_is_service_name_unique_returns_200_with_punctuation_added(admin_request, notify_db, notify_db_session, name):
    service = create_service(service_name="unique", email_from="unique")

    response = admin_request.get(
        "service.is_service_name_unique",
        _expected_status=200,
        name=name,
        service_id=service.id,
    )

    assert response == {"result": True}


@pytest.mark.parametrize(
    "name",
    [
        ("UNIQUE"),
    ],
)
def test_is_service_name_is_not_unique_returns_200_with_capitalization_while_unique_same_service(
    admin_request, notify_db, notify_db_session, name
):
    service = create_service(service_name="unique", email_from="unique")
    different_service_id = uuid.uuid4()

    response = admin_request.get(
        "service.is_service_name_unique",
        _expected_status=200,
        name=name,
        service_id=different_service_id,
    )

    assert response == {"result": False}

    response = admin_request.get(
        "service.is_service_name_unique",
        _expected_status=200,
        name=name,
        service_id=service.id,
    )

    assert response == {"result": True}


@pytest.mark.parametrize("name", [("existing name")])
def test_is_service_name_unique_returns_200_and_false_if_name_exist(admin_request, notify_db, notify_db_session, name):
    create_service(service_name="existing name", email_from="existing.name")
    different_service_id = uuid.uuid4()

    response = admin_request.get(
        "service.is_service_name_unique",
        _expected_status=200,
        name=name,
        service_id=different_service_id,
    )

    assert response == {"result": False}


@pytest.mark.parametrize("name, email_from", [("existing name", "existing.name")])
def test_is_service_email_from_unique_returns_200_and_false_if_email_from_exist_for_a_different_service(
    admin_request, notify_db, notify_db_session, name, email_from
):
    create_service(service_name="existing name", email_from="existing.name")
    different_service_id = uuid.uuid4()

    response = admin_request.get(
        "service.is_service_email_from_unique",
        _expected_status=200,
        service_id=different_service_id,
        email_from=email_from,
    )

    assert response == {"result": False}


def test_is_service_name_unique_returns_400_when_name_does_not_exist(admin_request):
    response = admin_request.get("service.is_service_name_unique", _expected_status=400)

    assert response["message"][1]["name"] == ["Can't be empty"]


def test_is_email_from_unique_returns_400_when_email_from_does_not_exist(admin_request):
    response = admin_request.get("service.is_service_email_from_unique", _expected_status=400)

    assert response["message"][0]["service_id"] == ["Can't be empty"]
    assert response["message"][1]["email_from"] == ["Can't be empty"]


def test_get_email_reply_to_addresses_when_there_are_no_reply_to_email_addresses(client, sample_service):
    response = client.get(
        "/service/{}/email-reply-to".format(sample_service.id),
        headers=[create_authorization_header()],
    )

    assert json.loads(response.get_data(as_text=True)) == []
    assert response.status_code == 200


def test_get_email_reply_to_addresses_with_one_email_address(client, notify_db, notify_db_session):
    service = create_service()
    create_reply_to_email(service, "test@mail.com")

    response = client.get(
        "/service/{}/email-reply-to".format(service.id),
        headers=[create_authorization_header()],
    )
    json_response = json.loads(response.get_data(as_text=True))

    assert len(json_response) == 1
    assert json_response[0]["email_address"] == "test@mail.com"
    assert json_response[0]["is_default"]
    assert json_response[0]["created_at"]
    assert not json_response[0]["updated_at"]
    assert response.status_code == 200


def test_get_email_reply_to_addresses_with_multiple_email_addresses(client, notify_db, notify_db_session):
    service = create_service()
    reply_to_a = create_reply_to_email(service, "test_a@mail.com")
    reply_to_b = create_reply_to_email(service, "test_b@mail.com", False)

    response = client.get(
        "/service/{}/email-reply-to".format(service.id),
        headers=[create_authorization_header()],
    )
    json_response = json.loads(response.get_data(as_text=True))

    assert len(json_response) == 2
    assert response.status_code == 200

    assert json_response[0]["id"] == str(reply_to_a.id)
    assert json_response[0]["service_id"] == str(reply_to_a.service_id)
    assert json_response[0]["email_address"] == "test_a@mail.com"
    assert json_response[0]["is_default"]
    assert json_response[0]["created_at"]
    assert not json_response[0]["updated_at"]

    assert json_response[1]["id"] == str(reply_to_b.id)
    assert json_response[1]["service_id"] == str(reply_to_b.service_id)
    assert json_response[1]["email_address"] == "test_b@mail.com"
    assert not json_response[1]["is_default"]
    assert json_response[1]["created_at"]
    assert not json_response[1]["updated_at"]


def test_verify_reply_to_email_address_should_send_verification_email(
    admin_request,
    notify_db,
    notify_db_session,
    mocker,
    verify_reply_to_address_email_template,
):
    service = create_service()
    mocked = mocker.patch("app.celery.provider_tasks.deliver_email.apply_async")
    data = {"email": "reply-here@example.gov.uk"}
    notify_service = verify_reply_to_address_email_template.service
    response = admin_request.post(
        "service.verify_reply_to_email_address",
        service_id=service.id,
        _data=data,
        _expected_status=201,
    )

    notification = Notification.query.first()
    assert notification.template_id == verify_reply_to_address_email_template.id
    assert response["data"] == {"id": str(notification.id)}
    mocked.assert_called_once_with([str(notification.id)], queue="notify-internal-tasks")
    assert notification.reply_to_text == notify_service.get_default_reply_to_email_address()


def test_verify_reply_to_email_address_doesnt_allow_duplicates(admin_request, notify_db, notify_db_session, mocker):
    data = {"email": "reply-here@example.gov.uk"}
    service = create_service()
    create_reply_to_email(service, "reply-here@example.gov.uk")
    response = admin_request.post(
        "service.verify_reply_to_email_address",
        service_id=service.id,
        _data=data,
        _expected_status=400,
    )
    assert response["message"] == {
        "0": "Your service already uses ",
        "1": "‘reply-here@example.gov.uk’ ",
        "2": "as an email reply-to address.",
    }


def test_add_service_reply_to_email_address(admin_request, sample_service):
    data = {"email_address": "new@reply.com", "is_default": True}
    response = admin_request.post(
        "service.add_service_reply_to_email_address",
        service_id=sample_service.id,
        _data=data,
        _expected_status=201,
    )

    results = ServiceEmailReplyTo.query.all()
    assert len(results) == 1
    assert response["data"] == results[0].serialize()


def test_add_service_reply_to_email_address_doesnt_allow_duplicates(admin_request, notify_db, notify_db_session, mocker):
    data = {"email_address": "reply-here@example.gov.uk", "is_default": True}
    service = create_service()
    create_reply_to_email(service, "reply-here@example.gov.uk")
    response = admin_request.post(
        "service.add_service_reply_to_email_address",
        service_id=service.id,
        _data=data,
        _expected_status=400,
    )
    assert response["message"] == {
        "0": "Your service already uses ",
        "1": "‘reply-here@example.gov.uk’ ",
        "2": "as an email reply-to address.",
    }


def test_add_service_reply_to_email_address_can_add_multiple_addresses(admin_request, sample_service):
    data = {"email_address": "first@reply.com", "is_default": True}
    admin_request.post(
        "service.add_service_reply_to_email_address",
        service_id=sample_service.id,
        _data=data,
        _expected_status=201,
    )
    second = {"email_address": "second@reply.com", "is_default": True}
    response = admin_request.post(
        "service.add_service_reply_to_email_address",
        service_id=sample_service.id,
        _data=second,
        _expected_status=201,
    )
    results = ServiceEmailReplyTo.query.all()
    assert len(results) == 2
    default = [x for x in results if x.is_default]
    assert response["data"] == default[0].serialize()
    first_reply_to_not_default = [x for x in results if not x.is_default]
    assert first_reply_to_not_default[0].email_address == "first@reply.com"


def test_add_service_reply_to_email_address_raise_exception_if_no_default(admin_request, sample_service):
    data = {"email_address": "first@reply.com", "is_default": False}
    response = admin_request.post(
        "service.add_service_reply_to_email_address",
        service_id=sample_service.id,
        _data=data,
        _expected_status=400,
    )
    assert response["message"] == "You must have at least one reply to email address as the default."


def test_add_service_reply_to_email_address_404s_when_invalid_service_id(admin_request, notify_db, notify_db_session):
    response = admin_request.post(
        "service.add_service_reply_to_email_address",
        service_id=uuid.uuid4(),
        _data={},
        _expected_status=404,
    )

    assert response["result"] == "error"
    assert response["message"] == "No result found"


def test_update_service_reply_to_email_address(admin_request, sample_service):
    original_reply_to = create_reply_to_email(service=sample_service, email_address="some@email.com")
    data = {"email_address": "changed@reply.com", "is_default": True}
    response = admin_request.post(
        "service.update_service_reply_to_email_address",
        service_id=sample_service.id,
        reply_to_email_id=original_reply_to.id,
        _data=data,
        _expected_status=200,
    )

    results = ServiceEmailReplyTo.query.all()
    assert len(results) == 1
    assert response["data"] == results[0].serialize()


def test_update_service_reply_to_email_address_returns_400_when_no_default(admin_request, sample_service):
    original_reply_to = create_reply_to_email(service=sample_service, email_address="some@email.com")
    data = {"email_address": "changed@reply.com", "is_default": False}
    response = admin_request.post(
        "service.update_service_reply_to_email_address",
        service_id=sample_service.id,
        reply_to_email_id=original_reply_to.id,
        _data=data,
        _expected_status=400,
    )

    assert response["message"] == "You must have at least one reply to email address as the default."


def test_update_service_reply_to_email_address_404s_when_invalid_service_id(admin_request, notify_db, notify_db_session):
    response = admin_request.post(
        "service.update_service_reply_to_email_address",
        service_id=uuid.uuid4(),
        reply_to_email_id=uuid.uuid4(),
        _data={},
        _expected_status=404,
    )

    assert response["result"] == "error"
    assert response["message"] == "No result found"


def test_delete_service_reply_to_email_address_archives_an_email_reply_to(sample_service, admin_request, notify_db_session):
    create_reply_to_email(service=sample_service, email_address="some@email.com")
    reply_to = create_reply_to_email(service=sample_service, email_address="some@email.com", is_default=False)

    admin_request.post(
        "service.delete_service_reply_to_email_address",
        service_id=sample_service.id,
        reply_to_email_id=reply_to.id,
    )
    assert reply_to.archived is True


def test_delete_service_reply_to_email_address_archives_default_reply_to_if_no_others_exist(
    admin_request, notify_db_session, sample_service
):
    reply_to = create_reply_to_email(service=sample_service, email_address="some@email.com")

    admin_request.post(
        "service.delete_service_reply_to_email_address",
        service_id=sample_service.id,
        reply_to_email_id=reply_to.id,
    )

    assert reply_to.archived is True


def test_delete_service_reply_to_email_address_returns_400_if_archiving_default_reply_to_and_others_exist(
    admin_request, notify_db_session, sample_service
):
    reply_to_1 = create_reply_to_email(service=sample_service, email_address="some_1@email.com")
    create_reply_to_email(service=sample_service, email_address="some_2@email.com")

    response = admin_request.post(
        "service.delete_service_reply_to_email_address",
        service_id=sample_service.id,
        reply_to_email_id=reply_to_1.id,
        _expected_status=400,
    )

    assert response == {
        "message": "You cannot delete a default email reply to address if other reply to addresses exist",
        "result": "error",
    }
    assert reply_to_1.archived is False


def test_get_email_reply_to_address(client, notify_db, notify_db_session):
    service = create_service()
    reply_to = create_reply_to_email(service, "test_a@mail.com")

    response = client.get(
        "/service/{}/email-reply-to/{}".format(service.id, reply_to.id),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )

    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True)) == reply_to.serialize()


def test_add_service_sms_sender_can_add_multiple_senders(client, notify_db_session):
    service = create_service()
    data = {
        "sms_sender": "second",
        "is_default": False,
    }
    response = client.post(
        "/service/{}/sms-sender".format(service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert resp_json["sms_sender"] == "second"
    assert not resp_json["is_default"]
    senders = ServiceSmsSender.query.all()
    assert len(senders) == 2


def test_add_service_sms_sender_when_it_is_an_inbound_number_updates_the_only_existing_non_archived_sms_sender(
    client, notify_db_session
):
    service = create_service_with_defined_sms_sender(sms_sender_value="fip_english")
    create_service_sms_sender(service=service, sms_sender="archived", is_default=False, archived=True)
    inbound_number = create_inbound_number(number="12345")
    data = {
        "sms_sender": str(inbound_number.id),
        "is_default": True,
        "inbound_number_id": str(inbound_number.id),
    }
    response = client.post(
        "/service/{}/sms-sender".format(service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 201
    updated_number = InboundNumber.query.get(inbound_number.id)
    assert updated_number.service_id == service.id
    resp_json = json.loads(response.get_data(as_text=True))
    assert resp_json["sms_sender"] == inbound_number.number
    assert resp_json["inbound_number_id"] == str(inbound_number.id)
    assert resp_json["is_default"]

    senders = dao_get_sms_senders_by_service_id(service.id)
    assert len(senders) == 1


def test_add_service_sms_sender_when_it_is_an_inbound_number_inserts_new_sms_sender_when_more_than_one(client, notify_db_session):
    service = create_service_with_defined_sms_sender(sms_sender_value="fip_english")
    create_service_sms_sender(service=service, sms_sender="second", is_default=False)
    inbound_number = create_inbound_number(number="12345")
    data = {
        "sms_sender": str(inbound_number.id),
        "is_default": True,
        "inbound_number_id": str(inbound_number.id),
    }
    response = client.post(
        "/service/{}/sms-sender".format(service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 201
    updated_number = InboundNumber.query.get(inbound_number.id)
    assert updated_number.service_id == service.id
    resp_json = json.loads(response.get_data(as_text=True))
    assert resp_json["sms_sender"] == inbound_number.number
    assert resp_json["inbound_number_id"] == str(inbound_number.id)
    assert resp_json["is_default"]

    senders = ServiceSmsSender.query.filter_by(service_id=service.id).all()
    assert len(senders) == 3


def test_add_service_sms_sender_switches_default(client, notify_db_session):
    service = create_service_with_defined_sms_sender(sms_sender_value="first")
    data = {
        "sms_sender": "second",
        "is_default": True,
    }
    response = client.post(
        "/service/{}/sms-sender".format(service.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert resp_json["sms_sender"] == "second"
    assert not resp_json["inbound_number_id"]
    assert resp_json["is_default"]
    sms_senders = ServiceSmsSender.query.filter_by(sms_sender="first").first()
    assert not sms_senders.is_default


def test_add_service_sms_sender_return_404_when_service_does_not_exist(client):
    data = {"sms_sender": "12345", "is_default": False}
    response = client.post(
        "/service/{}/sms-sender".format(uuid.uuid4()),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 404
    result = json.loads(response.get_data(as_text=True))
    assert result["result"] == "error"
    assert result["message"] == "No result found"


def test_update_service_sms_sender(client, notify_db_session):
    service = create_service()
    service_sms_sender = create_service_sms_sender(service=service, sms_sender="1235", is_default=False)
    data = {
        "sms_sender": "second",
        "is_default": False,
    }
    response = client.post(
        "/service/{}/sms-sender/{}".format(service.id, service_sms_sender.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 200
    resp_json = json.loads(response.get_data(as_text=True))
    assert resp_json["sms_sender"] == "second"
    assert not resp_json["inbound_number_id"]
    assert not resp_json["is_default"]


def test_update_service_sms_sender_switches_default(client, notify_db_session):
    service = create_service_with_defined_sms_sender(sms_sender_value="first")
    service_sms_sender = create_service_sms_sender(service=service, sms_sender="1235", is_default=False)
    data = {
        "sms_sender": "second",
        "is_default": True,
    }
    response = client.post(
        "/service/{}/sms-sender/{}".format(service.id, service_sms_sender.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 200
    resp_json = json.loads(response.get_data(as_text=True))
    assert resp_json["sms_sender"] == "second"
    assert not resp_json["inbound_number_id"]
    assert resp_json["is_default"]
    sms_senders = ServiceSmsSender.query.filter_by(sms_sender="first").first()
    assert not sms_senders.is_default


def test_update_service_sms_sender_does_not_allow_sender_update_for_inbound_number(client, notify_db_session):
    service = create_service()
    inbound_number = create_inbound_number("12345", service_id=service.id)
    service_sms_sender = create_service_sms_sender(
        service=service,
        sms_sender="1235",
        is_default=False,
        inbound_number_id=inbound_number.id,
    )
    data = {
        "sms_sender": "second",
        "is_default": True,
        "inbound_number_id": str(inbound_number.id),
    }
    response = client.post(
        "/service/{}/sms-sender/{}".format(service.id, service_sms_sender.id),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 400


def test_update_service_sms_sender_return_404_when_service_does_not_exist(client):
    data = {"sms_sender": "12345", "is_default": False}
    response = client.post(
        "/service/{}/sms-sender/{}".format(uuid.uuid4(), uuid.uuid4()),
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 404
    result = json.loads(response.get_data(as_text=True))
    assert result["result"] == "error"
    assert result["message"] == "No result found"


def test_delete_service_sms_sender_can_archive_sms_sender(admin_request, notify_db_session):
    service = create_service()
    service_sms_sender = create_service_sms_sender(service=service, sms_sender="5678", is_default=False)

    admin_request.post(
        "service.delete_service_sms_sender",
        service_id=service.id,
        sms_sender_id=service_sms_sender.id,
    )

    assert service_sms_sender.archived is True


def test_delete_service_sms_sender_returns_400_if_archiving_inbound_number(admin_request, notify_db_session):
    service = create_service_with_inbound_number(inbound_number="7654321")
    inbound_number = service.service_sms_senders[0]

    response = admin_request.post(
        "service.delete_service_sms_sender",
        service_id=service.id,
        sms_sender_id=service.service_sms_senders[0].id,
        _expected_status=400,
    )
    assert response == {
        "message": "You cannot delete an inbound number",
        "result": "error",
    }
    assert inbound_number.archived is False


def test_get_service_sms_sender_by_id(client, notify_db_session):
    service_sms_sender = create_service_sms_sender(service=create_service(), sms_sender="1235", is_default=False)
    response = client.get(
        "/service/{}/sms-sender/{}".format(service_sms_sender.service_id, service_sms_sender.id),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True)) == service_sms_sender.serialize()


def test_get_service_sms_sender_by_id_returns_404_when_service_does_not_exist(client, notify_db_session):
    service_sms_sender = create_service_sms_sender(service=create_service(), sms_sender="1235", is_default=False)
    response = client.get(
        "/service/{}/sms-sender/{}".format(uuid.uuid4(), service_sms_sender.id),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 404


def test_get_service_sms_sender_by_id_returns_404_when_sms_sender_does_not_exist(client, notify_db_session):
    service = create_service()
    response = client.get(
        "/service/{}/sms-sender/{}".format(service.id, uuid.uuid4()),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 404


def test_get_service_sms_senders_for_service(client, notify_db_session):
    service_sms_sender = create_service_sms_sender(service=create_service(), sms_sender="second", is_default=False)
    response = client.get(
        "/service/{}/sms-sender".format(service_sms_sender.service_id),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 200
    json_resp = json.loads(response.get_data(as_text=True))
    assert len(json_resp) == 2
    assert json_resp[0]["is_default"]
    assert json_resp[0]["sms_sender"] == current_app.config["FROM_NUMBER"]
    assert not json_resp[1]["is_default"]
    assert json_resp[1]["sms_sender"] == "second"


def test_get_service_sms_senders_for_service_returns_empty_list_when_service_does_not_exist(
    client,
):
    response = client.get(
        "/service/{}/sms-sender".format(uuid.uuid4()),
        headers=[("Content-Type", "application/json"), create_authorization_header()],
    )
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True)) == []


def test_get_organisation_for_service_id(admin_request, sample_service, sample_organisation):
    dao_add_service_to_organisation(sample_service, sample_organisation.id)
    response = admin_request.get("service.get_organisation_for_service", service_id=sample_service.id)
    assert response == sample_organisation.serialize()


def test_get_organisation_for_service_id_return_empty_dict_if_service_not_in_organisation(admin_request, fake_uuid):
    response = admin_request.get("service.get_organisation_for_service", service_id=fake_uuid)
    assert response == {}


def test_cancel_notification_for_service_raises_invalid_request_when_notification_is_not_found(
    admin_request,
    sample_service,
    fake_uuid,
):
    response = admin_request.post(
        "service.cancel_notification_for_service",
        service_id=sample_service.id,
        notification_id=fake_uuid,
        _expected_status=404,
    )
    assert response["message"] == "Notification not found"
    assert response["result"] == "error"


def test_cancel_notification_for_service_raises_invalid_request_when_notification_is_not_a_letter(
    admin_request,
    sample_notification,
):
    response = admin_request.post(
        "service.cancel_notification_for_service",
        service_id=sample_notification.service_id,
        notification_id=sample_notification.id,
        _expected_status=400,
    )
    assert response["message"] == "Notification cannot be cancelled - only letters can be cancelled"
    assert response["result"] == "error"


def test_get_monthly_notification_data_by_service(mocker, admin_request):
    dao_mock = mocker.patch(
        "app.service.rest.fact_notification_status_dao.fetch_monthly_notification_statuses_per_service",
        return_value=[],
    )

    start_date = "2019-01-01"
    end_date = "2019-06-17"

    response = admin_request.get(
        "service.get_monthly_notification_data_by_service",
        start_date=start_date,
        end_date=end_date,
    )

    dao_mock.assert_called_once_with(start_date, end_date)
    assert response == []


class TestGetSensitiveServiceids:
    def test_get_sensitive_service_id(self, client, notify_db, notify_db_session):
        service = create_service(service_name="service1", sensitive_service=True)
        auth_header = create_authorization_header()
        resp = client.get(
            "/service/sensitive-service-ids",
            headers=[auth_header],
        )
        assert resp.status_code == 200
        json_resp = resp.json
        assert json_resp["data"] == [str(service.id)]

    def test_no_sensitive_services(self, client, notify_db, notify_db_session):
        assert Service.query.count() == 0
        auth_header = create_authorization_header()
        resp = client.get(
            "/service/sensitive-service-ids",
            headers=[auth_header],
        )
        assert resp.status_code == 200
        json_resp = resp.json
        assert json_resp["data"] == []


class TestAnnualLimitStats:
    def test_get_annual_limit_stats(self, admin_request, sample_service, mocker):
        mock_get_stats = mocker.patch(
            "app.service.rest.get_annual_limit_notifications_v2",
            return_value={
                "email_delivered_today": 5,
                "email_failed_today": 1,
                "sms_delivered_today": 3,
                "sms_failed_today": 2,
                "total_email_fiscal_year_to_yesterday": 100,
                "total_sms_fiscal_year_to_yesterday": 200,
            },
        )

        response = admin_request.get("service.get_annual_limit_stats", service_id=sample_service.id)

        assert response == {
            "email_delivered_today": 5,
            "email_failed_today": 1,
            "sms_delivered_today": 3,
            "sms_failed_today": 2,
            "total_email_fiscal_year_to_yesterday": 100,
            "total_sms_fiscal_year_to_yesterday": 200,
        }

        mock_get_stats.assert_called_once_with((sample_service.id))


class TestAddUserToService:
    def test_add_user_to_service_with_send_permissions_succeeds(self, notify_api, notify_db_session):
        """Test adding a user to a service with send permissions"""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                service = create_service()
                # Create a user who is not part of the service
                user_to_add = User(
                    name="New User",
                    email_address="new_user@cds-snc.ca",
                    password="password",
                    mobile_number="+4477123456",
                )
                save_model_user(user_to_add)

                data = {
                    "permissions": [
                        {"permission": "send_emails"},
                        {"permission": "send_letters"},
                        {"permission": "send_texts"},
                    ]
                }

                auth_header = create_authorization_header()
                resp = client.post(
                    "/service/{}/users/{}".format(service.id, user_to_add.id),
                    headers=[("Content-Type", "application/json"), auth_header],
                    data=json.dumps(data),
                )

                assert resp.status_code == 201
                json_resp = json.loads(resp.get_data(as_text=True))
                assert str(user_to_add.id) in json_resp["data"]["users"]

    def test_add_user_to_service_with_manage_permissions_succeeds(self, notify_api, notify_db_session):
        """Test adding a user to a service with management permissions"""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                service = create_service()
                user_to_add = User(
                    name="Manager User",
                    email_address="manager@cds-snc.ca",
                    password="password",
                    mobile_number="+4477999888",
                )
                save_model_user(user_to_add)

                data = {
                    "permissions": [
                        {"permission": "manage_users"},
                        {"permission": "manage_templates"},
                        {"permission": "manage_settings"},
                    ]
                }

                auth_header = create_authorization_header()
                resp = client.post(
                    "/service/{}/users/{}".format(service.id, user_to_add.id),
                    headers=[("Content-Type", "application/json"), auth_header],
                    data=json.dumps(data),
                )

                assert resp.status_code == 201
                json_resp = json.loads(resp.get_data(as_text=True))
                assert str(user_to_add.id) in json_resp["data"]["users"]

                # Check user has correct permissions by calling the user endpoint
                resp = client.get(
                    url_for("user.get_user", user_id=user_to_add.id),
                    headers=[("Content-Type", "application/json"), auth_header],
                )

                assert resp.status_code == 200
                json_resp = json.loads(resp.get_data(as_text=True))
                permissions = json_resp["data"]["permissions"][str(service.id)]
                expected_permissions = ["manage_users", "manage_templates", "manage_settings"]
                assert sorted(permissions) == sorted(expected_permissions)

    def test_add_existing_user_of_service_returns_409(self, notify_api, notify_db_session):
        """Test that adding an existing user to a service returns a 409 conflict"""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                service = create_service()
                existing_user = service.users[0]

                data = {"permissions": [{"permission": "send_emails"}]}

                auth_header = create_authorization_header()
                resp = client.post(
                    "/service/{}/users/{}".format(service.id, existing_user.id),
                    headers=[("Content-Type", "application/json"), auth_header],
                    data=json.dumps(data),
                )

                assert resp.status_code == 409
                result = json.loads(resp.get_data(as_text=True))
                assert result["result"] == "error"
                assert f"User id: {existing_user.id}" in result["message"]

    def test_add_user_to_non_existent_service_returns_404(self, notify_api, notify_db_session):
        """Test that adding a user to a non-existent service returns a 404"""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                user = User(
                    name="Valid User",
                    email_address="valid_user@cds-snc.ca",
                    password="password",
                    mobile_number="+4477123123",
                )
                save_model_user(user)

                fake_service_id = uuid.uuid4()
                data = {"permissions": [{"permission": "send_emails"}]}

                auth_header = create_authorization_header()
                resp = client.post(
                    "/service/{}/users/{}".format(fake_service_id, user.id),
                    headers=[("Content-Type", "application/json"), auth_header],
                    data=json.dumps(data),
                )

                assert resp.status_code == 404
                result = json.loads(resp.get_data(as_text=True))
                assert result["result"] == "error"
                assert result["message"] == "No result found"

    def test_add_non_existent_user_to_service_returns_404(self, notify_api, notify_db_session):
        """Test that adding a non-existent user to a service returns a 404"""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                service = create_service()
                fake_user_id = uuid.uuid4()

                data = {"permissions": [{"permission": "send_emails"}]}

                auth_header = create_authorization_header()
                resp = client.post(
                    "/service/{}/users/{}".format(service.id, fake_user_id),
                    headers=[("Content-Type", "application/json"), auth_header],
                    data=json.dumps(data),
                )

                assert resp.status_code == 404
                result = json.loads(resp.get_data(as_text=True))
                assert result["result"] == "error"
                assert result["message"] == "No result found"

    def test_add_user_to_service_without_permissions_returns_400(self, notify_api, notify_db_session):
        """Test that adding a user without specifying permissions returns a 400"""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                service = create_service()
                user = User(
                    name="Valid User",
                    email_address="valid_user@cds-snc.ca",
                    password="password",
                    mobile_number="+4477123123",
                )
                save_model_user(user)

                # Missing permissions in the request
                data = {}

                auth_header = create_authorization_header()
                resp = client.post(
                    "/service/{}/users/{}".format(service.id, user.id),
                    headers=[("Content-Type", "application/json"), auth_header],
                    data=json.dumps(data),
                )

                assert resp.status_code == 400
