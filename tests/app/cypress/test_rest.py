import json
from datetime import datetime, timedelta

from app.models import User
from tests import create_cypres_authorization_header
from tests.conftest import set_config_values

EMAIL_PREFIX = "notify-ui-tests+ag_"


def test_create_test_user(client, sample_service_cypress):
    auth_header = create_cypres_authorization_header()

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
    auth_header = create_cypres_authorization_header()

    resp = client.post(
        "/cypress/create_user/{}".format("email-suffix"),
        headers=[auth_header],
        content_type="application/json",
    )

    assert resp.status_code == 400


def test_create_test_user_fails_in_prod(client, notify_api, sample_service_cypress):
    with set_config_values(notify_api, {"NOTIFY_ENVIRONMENT": "production"}):
        auth_header = create_cypres_authorization_header()

        resp = client.post(
            "/cypress/create_user/{}".format("email-suffix"),
            headers=[auth_header],
            content_type="application/json",
        )

        assert resp.status_code == 403


def test_cleanup_stale_users(client, sample_service_cypress, cypress_user, notify_db):
    auth_header = create_cypres_authorization_header()
    resp = client.post(
        "/cypress/create_user/{}".format("emailsuffix"),
        headers=[auth_header],
        content_type="application/json",
    )
    data = json.loads(resp.data)
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
    auth_header = create_cypres_authorization_header()
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


# def test_cleanup_stale_users_no_stale_users(test_client):
#     response = test_client.get('/cleanup')
#     data = json.loads(response.data)

#     assert response.status_code == 201
#     assert data['message'] == "Clean up complete"

# def test_destroy_test_user(test_client):
#     # Create a test user
#     test_user = User(
#         email_address=f"{EMAIL_PREFIX}testuser@cds-snc.ca",
#         password='password',
#         mobile_number='1234567890',
#         state='active',
#         blocked=False
#     )
#     db.session.add(test_user)
#     db.session.commit()

#     _destroy_test_user('testuser')

#     # Verify the test user has been deleted
#     user = User.query.filter_by(email_address=f"{EMAIL_PREFIX}testuser@cds-snc.ca").first()
#     assert user is None
