from unittest.mock import patch

from sqlalchemy.exc import IntegrityError

from app import db
from app.dao.services_dao import dao_add_user_to_service
from app.models import Permission, ServiceUser


# This test demonstrates the UniqueViolation bug that occurs when adding a user to a service
# The bug happens due to a race condition in the session management where service.users.append(user)
# adds the user to the service but before the transaction is committed, we try to query for the ServiceUser
# record, which triggers SQLAlchemy to auto-flush the session, causing a uniqueness constraint violation
def test_dao_add_user_to_service_with_race_condition(sample_service, sample_user):
    # Make sure user is not already part of the service
    sample_service.users.remove(sample_user)
    db.session.commit()

    # Setup our mock to simulate the race condition
    # original_dao_get_service_user = dao_get_service_user

    def mock_dao_get_service_user(user_id, service_id):
        # This mock simulates what happens when SQLAlchemy tries to auto-flush
        # the session to get the ServiceUser that was just created in memory
        # but not yet committed to the database

        # First, we append the user to the service (this happens in dao_add_user_to_service)
        # but this only creates the relationship in memory, not in the database yet

        # When we call dao_get_service_user, it will try to find the record in the database
        # but it's not there yet, so SQLAlchemy will try to flush the session
        # which will cause a uniqueness constraint violation

        # To simulate this race condition, we'll raise the IntegrityError
        # that would be raised when SQLAlchemy tries to flush the session
        raise IntegrityError(
            statement="INSERT INTO service_users (user_id, service_id) VALUES (:user_id, :service_id)",
            params={"user_id": user_id, "service_id": service_id},
            orig=Exception(
                'duplicate key value violates unique constraint "uix_user_to_service"\nDETAIL:  Key (user_id, service_id)=(...) already exists.'
            ),
        )

    # Apply the patch to simulate the race condition
    with patch("app.dao.service_user_dao.dao_get_service_user", side_effect=mock_dao_get_service_user):
        # In the original buggy code, this would raise IntegrityError
        # In the fixed code, it should handle the case properly
        permissions = [Permission(service_id=sample_service.id, user_id=sample_user.id, permission="manage_users")]

        # This should not raise an exception with the fixed code
        dao_add_user_to_service(sample_service, sample_user, permissions=permissions)

        # Verify the user was added to the service
        assert sample_user in sample_service.users

        # Check if the permissions were set correctly
        service_user = ServiceUser.query.filter_by(user_id=sample_user.id, service_id=sample_service.id).one()
        assert len(service_user.get_permissions()) == 1
        assert "manage_users" in service_user.get_permissions()
