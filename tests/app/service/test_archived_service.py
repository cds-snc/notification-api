import uuid
from datetime import datetime

import pytest
from flask import current_app
from freezegun import freeze_time

from app import db
from app.dao.api_key_dao import expire_api_key
from app.dao.services_dao import dao_archive_service
from app.dao.templates_dao import dao_update_template
from app.models import Service
from tests import create_authorization_header, unwrap_function
from tests.app.db import create_api_key, create_template


def test_archive_only_allows_post(client, notify_db_session):
    auth_header = create_authorization_header()
    response = client.get("/service/{}/archive".format(uuid.uuid4()), headers=[auth_header])
    assert response.status_code == 405


def test_archive_service_errors_with_bad_service_id(client, notify_db_session):
    auth_header = create_authorization_header()
    response = client.post("/service/{}/archive".format(uuid.uuid4()), headers=[auth_header])
    assert response.status_code == 404


def test_archiving_service_sends_deletion_email_to_all_users(client, sample_service, mocker):
    """Test that archiving a service sends deletion email to all service users"""
    # Mock the send_notification_to_service_users function
    mock_send_notification = mocker.patch("app.service.rest.send_notification_to_service_users")
    service_name = sample_service.name

    auth_header = create_authorization_header()
    response = client.post("/service/{}/archive".format(sample_service.id), headers=[auth_header])

    assert response.status_code == 204

    # Verify that send_notification_to_service_users was called with correct parameters
    mock_send_notification.assert_called_once_with(
        service_id=sample_service.id,
        template_id=current_app.config["SERVICE_DEACTIVATED_TEMPLATE_ID"],
        personalisation={
            "service_name": service_name,
        },
    )


def test_deactivating_inactive_service_does_nothing(client, sample_service):
    auth_header = create_authorization_header()
    sample_service.active = False
    response = client.post("/service/{}/archive".format(sample_service.id), headers=[auth_header])
    assert response.status_code == 204
    assert sample_service.name == "Sample service"


@pytest.fixture
@freeze_time("2018-04-21 14:00")
def archived_service(client, notify_db, sample_service, mocker):
    mocker.patch("app.service.rest.send_notification_to_service_users")
    create_template(sample_service, template_name="a")
    create_template(sample_service, template_name="b")
    create_api_key(sample_service)
    create_api_key(sample_service)

    notify_db.session.commit()

    auth_header = create_authorization_header()
    response = client.post("/service/{}/archive".format(sample_service.id), headers=[auth_header])
    assert response.status_code == 204
    assert response.data == b""
    return sample_service


def test_deactivating_service_changes_name_and_email(archived_service):
    assert archived_service.name == "_archived_2018-04-21_14:00:00_Sample service"
    assert archived_service.email_from == "_archived_2018-04-21_14:00:00_sample.service"


def test_deactivating_service_revokes_api_keys(archived_service):
    assert len(archived_service.api_keys) == 2
    for key in archived_service.api_keys:
        assert key.expiry_date is not None
        assert key.version == 2


def test_deactivating_service_archives_templates(archived_service):
    assert len(archived_service.templates) == 2
    for template in archived_service.templates:
        assert template.archived is True
        assert template.version == 2


def test_deactivating_service_creates_history(archived_service):
    ServiceHistory = Service.get_history_model()
    history = ServiceHistory.query.filter_by(id=archived_service.id).order_by(ServiceHistory.version.desc()).first()

    assert history.version == 2
    assert history.active is False


@pytest.fixture
def archived_service_with_deleted_stuff(client, sample_service, mocker):
    mocker.patch("app.service.rest.send_notification_to_service_users")
    with freeze_time("2001-01-01"):
        template = create_template(sample_service, template_name="a")
        api_key = create_api_key(sample_service)

        expire_api_key(sample_service.id, api_key.id)

        template.archived = True
        dao_update_template(template)

    with freeze_time("2002-02-02"):
        auth_header = create_authorization_header()
        response = client.post("/service/{}/archive".format(sample_service.id), headers=[auth_header])

    assert response.status_code == 204
    assert response.data == b""
    return sample_service


def test_deactivating_service_doesnt_affect_existing_archived_templates(
    archived_service_with_deleted_stuff,
):
    assert archived_service_with_deleted_stuff.templates[0].archived is True
    assert archived_service_with_deleted_stuff.templates[0].updated_at == datetime(2001, 1, 1, 0, 0, 0)
    assert archived_service_with_deleted_stuff.templates[0].version == 2


def test_deactivating_service_doesnt_affect_existing_revoked_api_keys(
    archived_service_with_deleted_stuff,
):
    assert archived_service_with_deleted_stuff.api_keys[0].expiry_date == datetime(2001, 1, 1, 0, 0, 0)
    assert archived_service_with_deleted_stuff.api_keys[0].version == 2


def test_deactivating_service_rolls_back_everything_on_error(sample_service, sample_api_key, sample_template):
    unwrapped_deactive_service = unwrap_function(dao_archive_service)

    unwrapped_deactive_service(sample_service.id)

    assert sample_service in db.session.dirty
    assert sample_api_key in db.session.dirty
    assert sample_template in db.session.dirty
