import uuid

import pytest
from freezegun import freeze_time

from app.models import Service
from tests import create_authorization_header
from tests.app.db import create_service, create_user


@pytest.mark.parametrize("endpoint", ["suspend", "resume"])
def test_only_allows_post(client, endpoint):
    auth_header = create_authorization_header()
    response = client.get("/service/{}/{}".format(uuid.uuid4(), endpoint), headers=[auth_header])
    assert response.status_code == 405


@pytest.mark.parametrize("endpoint", ["suspend", "resume"])
def test_returns_404_when_service_does_not_exist(client, sample_service, endpoint):
    auth_header = create_authorization_header()
    response = client.post("/service/{}/{}".format(uuid.uuid4(), endpoint), headers=[auth_header])
    assert response.status_code == 404


@pytest.mark.parametrize("action, active", [("suspend", False), ("resume", True)])
def test_has_not_effect_when_service_is_already_that_state(client, sample_service, action, active, mocker):
    mocked = mocker.patch("app.service.rest.dao_{}_service".format(action))
    sample_service.active = active
    auth_header = create_authorization_header()
    response = client.post("/service/{}/{}".format(sample_service.id, action), headers=[auth_header])
    assert response.status_code == 204
    mocked.assert_not_called()
    assert sample_service.active == active


@freeze_time("2001-01-01T23:59:00")
def test_suspending_service_revokes_api_keys(client, sample_service, sample_api_key):
    auth_header = create_authorization_header()
    response = client.post("/service/{}/suspend".format(sample_service.id), headers=[auth_header])
    assert response.status_code == 204
    assert sample_api_key.expiry_date is None


def test_resume_service_leaves_api_keys_revokes(client, sample_service, sample_api_key):
    with freeze_time("2001-10-22T11:59:00"):
        auth_header = create_authorization_header()
        client.post("/service/{}/suspend".format(sample_service.id), headers=[auth_header])
    with freeze_time("2001-10-22T13:59:00"):
        auth_header = create_authorization_header()
        response = client.post("/service/{}/resume".format(sample_service.id), headers=[auth_header])
        assert response.status_code == 204
        assert sample_api_key.expiry_date is None


@pytest.mark.parametrize("action, original_state", [("suspend", True), ("resume", False)])
def test_service_history_is_created(client, sample_service, action, original_state):
    sample_service.active = original_state
    auth_header = create_authorization_header()
    response = client.post("/service/{}/{}".format(sample_service.id, action), headers=[auth_header])
    ServiceHistory = Service.get_history_model()
    history = ServiceHistory.query.filter_by(id=sample_service.id).order_by(ServiceHistory.version.desc()).first()

    assert response.status_code == 204
    assert history.version == 2
    assert history.active != original_state


@freeze_time("2025-10-21 12:00:00")
def test_suspend_service_without_user_id_leaves_suspended_by_none(client, notify_db_session):
    """Suspending a service via REST without supplying user_id should not set suspended_by_id."""
    user = create_user()
    service = create_service(user=user)

    # Suspend without user_id
    resp = client.post(
        f"/service/{service.id}/suspend",
        headers=[create_authorization_header()],
    )
    assert resp.status_code == 204

    svc = Service.query.get(service.id)
    assert svc.active is False
    assert svc.suspended_at is not None
    # suspended_by_id should remain unset when no user_id provided
    assert svc.suspended_by_id is None
