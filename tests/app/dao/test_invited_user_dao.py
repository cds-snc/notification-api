from datetime import datetime, timedelta
import uuid

import pytest
from sqlalchemy.orm.exc import NoResultFound

from app import db

from app.models import InvitedUser

from app.dao.invited_user_dao import (
    save_invited_user,
    get_invited_user,
    get_invited_users_for_service,
    get_invited_user_by_id,
    delete_invitations_created_more_than_two_days_ago,
)


def test_create_invited_user(notify_db_session, sample_service):
    email_address = 'invited_user@service.gov.uk'
    service = sample_service()
    invite_from = service.users[0]

    data = {
        'service': service,
        'email_address': email_address,
        'from_user': invite_from,
        'permissions': 'send_messages,manage_service',
        'folder_permissions': [],
    }

    invited_user = InvitedUser(**data)
    save_invited_user(invited_user)

    try:
        assert invited_user.email_address == email_address
        assert invited_user.from_user == invite_from
        permissions = invited_user.get_permissions()
        assert len(permissions) == 2
        assert 'send_messages' in permissions
        assert 'manage_service' in permissions
        assert invited_user.folder_permissions == []
    finally:
        notify_db_session.session.delete(invited_user)
        notify_db_session.session.commit()


def test_create_invited_user_sets_default_folder_permissions_of_empty_list(notify_db_session, sample_service):
    service = sample_service()
    data = {
        'service': service,
        'email_address': 'invited_user@service.gov.uk',
        'from_user': service.users[0],
        'permissions': 'send_messages,manage_service',
    }

    invited_user = InvitedUser(**data)
    save_invited_user(invited_user)

    try:
        assert invited_user.folder_permissions == []
    finally:
        notify_db_session.session.delete(invited_user)
        notify_db_session.session.commit()


def test_get_invited_user_by_service_and_id(sample_invited_user):
    invited_user = sample_invited_user()
    from_db = get_invited_user(invited_user.service.id, invited_user.id)
    assert from_db == invited_user


def test_get_invited_user_by_id(sample_invited_user):
    invited_user = sample_invited_user()
    from_db = get_invited_user_by_id(invited_user.id)
    assert from_db == invited_user


def test_get_unknown_invited_user_returns_none(sample_service):
    unknown_id = uuid.uuid4()

    with pytest.raises(NoResultFound) as e:
        get_invited_user(sample_service().id, unknown_id)
    assert 'No row was found when one' in str(e.value)


def test_get_invited_users_for_service(sample_service, sample_invited_user):
    invites = []
    service = sample_service()

    for i in range(0, 5):
        email = f'invited_user_{i}@service.gov.uk'
        invited_user = sample_invited_user(service, email)
        invites.append(invited_user)

    all_from_db = get_invited_users_for_service(service.id)
    assert len(all_from_db) == 5
    for invite in invites:
        assert invite in all_from_db


def test_get_invited_users_for_service_that_has_no_invites(sample_service):
    invites = get_invited_users_for_service(sample_service().id)
    assert len(invites) == 0


def test_save_invited_user_sets_status_to_cancelled(notify_db_session, sample_invited_user):
    invited_user = sample_invited_user()
    assert invited_user.status == 'pending'

    invited_user.status = 'cancelled'
    save_invited_user(invited_user)

    assert notify_db_session.session.get(InvitedUser, invited_user.id).status == 'cancelled'


def test_should_delete_all_invitations_more_than_two_days_old(notify_db_session, sample_invited_user):
    right_now = datetime.utcnow()
    invited_user1_id = sample_invited_user(created_at=right_now - timedelta(hours=48, minutes=1)).id
    invited_user2_id = sample_invited_user(created_at=right_now - timedelta(hours=48, minutes=1)).id

    assert delete_invitations_created_more_than_two_days_ago() == 2
    assert notify_db_session.session.get(InvitedUser, invited_user1_id) is None
    assert notify_db_session.session.get(InvitedUser, invited_user2_id) is None


def test_should_not_delete_invitations_less_than_two_days_old(notify_db_session, sample_invited_user):
    right_now = datetime.utcnow()
    invited_user1_id = sample_invited_user(created_at=right_now - timedelta(hours=47, minutes=59)).id
    invited_user2_id = sample_invited_user(created_at=right_now - timedelta(hours=48, minutes=1)).id

    delete_invitations_created_more_than_two_days_ago()

    assert notify_db_session.session.get(InvitedUser, invited_user1_id) is not None
    assert notify_db_session.session.get(InvitedUser, invited_user2_id) is None


def make_invitation(user, service, age=timedelta(hours=0), email_address='test@test.com'):
    verify_code = InvitedUser(
        email_address=email_address,
        from_user=user,
        service=service,
        status='pending',
        created_at=datetime.utcnow() - age,
        permissions='manage_settings',
        folder_permissions=[str(uuid.uuid4())],
    )
    db.session.add(verify_code)
    db.session.commit()
