import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch

from app.models import User
from tests import create_cypress_authorization_header
from tests.app.conftest import create_sample_template, create_template_category
from tests.conftest import set_config_values

EMAIL_PREFIX = os.getenv("CYPRESS_USER_EMAIL_PREFIX", "notify-ui-tests+ag_")


def test_create_test_user(client, sample_service_cypress):
    auth_header = create_cypress_authorization_header()

    resp = client.post(
        "/cypress/create_user/{}".format("emailsuffix"),
        headers=[auth_header],
        content_type="application/json",
    )

    data = json.loads(resp.data)

    assert resp.status_code == 201
    assert "regular" in data
    assert "admin" in data
    assert data["regular"]["email_address"] == f"{EMAIL_PREFIX}emailsuffix@cds-snc.ca"
    assert data["admin"]["email_address"] == f"{EMAIL_PREFIX}emailsuffix_admin@cds-snc.ca"

    # verify users were created in the DB
    user = User.query.filter_by(email_address=f"{EMAIL_PREFIX}emailsuffix@cds-snc.ca").first()
    assert user is not None

    user = User.query.filter_by(email_address=f"{EMAIL_PREFIX}emailsuffix_admin@cds-snc.ca").first()
    assert user is not None


def test_create_test_user_fails_bad_chars(client, sample_service_cypress):
    auth_header = create_cypress_authorization_header()

    resp = client.post(
        "/cypress/create_user/{}".format("email-suffix"),
        headers=[auth_header],
        content_type="application/json",
    )

    assert resp.status_code == 400


def test_create_test_user_fails_in_prod(client, notify_api, sample_service_cypress):
    with set_config_values(notify_api, {"NOTIFY_ENVIRONMENT": "production"}):
        auth_header = create_cypress_authorization_header()

        resp = client.post(
            "/cypress/create_user/{}".format("email-suffix"),
            headers=[auth_header],
            content_type="application/json",
        )

        assert resp.status_code == 403


def test_cleanup_stale_users(client, sample_service_cypress, cypress_user, notify_db):
    auth_header = create_cypress_authorization_header()
    resp = client.post(
        "/cypress/create_user/{}".format("emailsuffix"),
        headers=[auth_header],
        content_type="application/json",
    )

    assert resp.status_code == 201
    # verify users were created in the DB
    user = User.query.filter_by(email_address=f"{EMAIL_PREFIX}emailsuffix@cds-snc.ca").first()
    assert user is not None
    user2 = User.query.filter_by(email_address=f"{EMAIL_PREFIX}emailsuffix_admin@cds-snc.ca").first()
    assert user2 is not None
    # update created_at time so they can be cleaned up
    user.created_at = datetime.utcnow() - timedelta(days=30)
    user2.created_at = datetime.utcnow() - timedelta(days=30)
    notify_db.session.add(user)
    notify_db.session.add(user2)
    notify_db.session.commit()

    # clean up users
    auth_header = create_cypress_authorization_header()
    resp = client.get(
        "/cypress/cleanup",
        headers=[auth_header],
        content_type="application/json",
    )
    data = json.loads(resp.data)

    assert resp.status_code == 201
    assert data["message"] == "Clean up complete"

    # Verify the stale user has been deleted
    user = User.query.filter_by(email_address=f"{EMAIL_PREFIX}emailsuffix@cds-snc.ca").first()
    assert user is None

    user = User.query.filter_by(email_address=f"{EMAIL_PREFIX}emailsuffix_admin@cds-snc.ca").first()
    assert user is None


def test_delete_template_categories_by_user_id_success(client, cypress_user, notify_db, notify_db_session):
    cascade = "true"
    path = f"/cypress/template-categories/cleanup/{cypress_user.id}?cascade={cascade}"
    auth_header = create_cypress_authorization_header()

    category = create_template_category(notify_db, notify_db_session, created_by_id=cypress_user.id)

    with patch("app.cypress.rest.dao_delete_template_category_by_id") as mock_delete:
        mock_delete.return_value = None  # Simulate successful deletion
        response = client.post(path, headers=[auth_header], content_type="application/json")

    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert resp_json["message"] == "Template category clean up complete 1 of 1 deleted."

    # Verify the mock was called for each template category
    assert mock_delete.call_count == 1
    mock_delete.assert_any_call(category.id, cascade=True)


def test_delete_template_categories_by_user_id_exception(client, cypress_user, notify_db, notify_db_session):
    path = f"/cypress/template-categories/cleanup/{cypress_user.id}"
    auth_header = create_cypress_authorization_header()

    # Mock template categories created by the user
    categories = [
        create_template_category(notify_db, notify_db_session, name_en="1", name_fr="1", created_by_id=cypress_user.id),
        create_template_category(notify_db, notify_db_session, created_by_id=cypress_user.id),
    ]
    create_sample_template(notify_db, notify_db_session, template_category=categories[0])

    with patch("app.cypress.rest.dao_delete_template_category_by_id", side_effect=Exception("bad things happened")):
        response = client.post(path, headers=[auth_header], content_type="application/json")

    assert response.status_code == 207
    resp_json = json.loads(response.get_data(as_text=True))
    assert resp_json["message"] == "Template category clean up complete 0 of 2 deleted."
    assert len(resp_json["failed_category_ids"]) == 2
