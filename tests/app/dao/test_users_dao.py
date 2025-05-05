import uuid

import pytest

from app.constants import SMS_TYPE
from app.dao.users_dao import (
    get_user_by_id,
    delete_model_user,
    delete_codes_older_created_more_than_a_day_ago,
    create_secret_code,
    user_can_be_archived,
    get_user_by_identity_provider_user_id,
)
from app.model import User
from app.models import VerifyCode
from datetime import datetime, timedelta
from sqlalchemy import or_, select
from sqlalchemy.exc import DataError
from sqlalchemy.orm.exc import NoResultFound
from tests.app.db import create_permissions


@pytest.fixture
def test_email():
    return f'{uuid.uuid4()}y@notifications.va.gov'


@pytest.fixture
def test_name():
    return f'Test User {uuid.uuid4()}'


def test_create_user_no_longer_fails_when_password_is_empty(
    notify_db_session,
    test_email,
    test_name,
):
    data = {'name': test_name, 'email_address': test_email}

    user = User(**data)
    user.save_to_db()

    loaded_user = notify_db_session.session.get(User, user.id)
    assert loaded_user

    # Teardown
    if user:
        notify_db_session.session.delete(user)
        notify_db_session.session.commit()


@pytest.mark.serial
def test_get_all_users(
    notify_api,
    sample_user,
    test_email,
):
    sample_user(email=test_email)
    sample_user(email=f'get_all{test_email}')

    # Cannot be ran in parallel - Gathers all users if no id is specified
    assert len(get_user_by_id()) == 2


def test_get_user(
    sample_user,
    test_email,
):
    user = sample_user(email=test_email)
    assert get_user_by_id(user_id=user.id).email_address == test_email


def test_get_user_not_exists(notify_db_session, fake_uuid):
    with pytest.raises(NoResultFound):
        get_user_by_id(user_id=fake_uuid)


def test_get_user_invalid_id(notify_db_session):
    with pytest.raises(DataError):
        get_user_by_id(user_id='blah')


def test_delete_users(
    notify_db_session,
    sample_user,
):
    user = sample_user()
    delete_model_user(user)

    assert notify_db_session.session.get(User, user.id) is None


def make_verify_code(
    notify_db_session, user, age=timedelta(hours=0), expiry_age=timedelta(0), code='12335', code_used=False
):
    verify_code = VerifyCode(
        code_type=SMS_TYPE,
        code=code,
        created_at=datetime.utcnow() - age,
        expiry_datetime=datetime.utcnow() - expiry_age,
        user=user,
        code_used=code_used,
    )
    notify_db_session.session.add(verify_code)
    notify_db_session.session.commit()
    return verify_code


def test_should_delete_all_verification_codes_more_than_one_day_old(
    notify_db_session,
    sample_user,
):
    user_0 = sample_user()
    user_1 = sample_user()

    make_verify_code(notify_db_session, user_0, age=timedelta(hours=24), code='54321')
    make_verify_code(notify_db_session, user_1, age=timedelta(hours=24), code='54321')
    stmt = select(VerifyCode).where(or_(VerifyCode.user_id == user_0.id, VerifyCode.user_id == user_1.id))
    assert len(notify_db_session.session.scalars(stmt).all()) == 2
    delete_codes_older_created_more_than_a_day_ago()
    assert len(notify_db_session.session.scalars(stmt).all()) == 0


def test_create_secret_code_different_subsequent_codes():
    code1 = create_secret_code()
    code2 = create_secret_code()
    assert code1 != code2


def test_create_secret_code_returns_5_digits():
    code = create_secret_code()
    assert len(str(code)) == 5


def test_user_can_be_archived_if_they_do_not_belong_to_any_services(
    sample_user,
):
    user = sample_user()
    assert user.services == []
    assert user_can_be_archived(user)


def test_user_can_be_archived_if_they_do_not_belong_to_any_active_services(
    sample_user,
    sample_service,
):
    user = sample_user()
    service = sample_service()
    user.services = [service]
    service.active = False

    assert len(user.services) == 1
    assert user_can_be_archived(user)


def test_user_can_be_archived_if_the_other_service_members_have_the_manage_settings_permission(
    sample_service,
    sample_user,
):
    service = sample_service()
    user_1 = sample_user()
    user_2 = sample_user()
    user_3 = sample_user()

    service.users = [user_1, user_2, user_3]

    create_permissions(user_1, service, 'manage_settings')
    create_permissions(user_2, service, 'manage_settings', 'view_activity')
    create_permissions(user_3, service, 'manage_settings', 'send_emails', 'send_letters', 'send_texts')

    assert len(service.users) == 3
    assert user_can_be_archived(user_1)


def test_user_cannot_be_archived_if_they_belong_to_a_service_with_no_other_active_users(
    sample_service,
    sample_user,
):
    service = sample_service()
    active_user = sample_user()
    pending_user = sample_user(state='pending')
    inactive_user = sample_user(state='inactive')

    service.users = [active_user, pending_user, inactive_user]

    assert len(service.users) == 3
    assert not user_can_be_archived(active_user)


def test_user_cannot_be_archived_if_the_other_service_members_do_not_have_the_manage_setting_permission(
    sample_service,
    sample_user,
):
    service = sample_service()
    active_user = sample_user()
    pending_user = sample_user()
    inactive_user = sample_user()

    service.users = [active_user, pending_user, inactive_user]

    create_permissions(active_user, service, 'manage_settings')
    create_permissions(pending_user, service, 'view_activity')
    create_permissions(inactive_user, service, 'send_emails', 'send_letters', 'send_texts')

    assert len(service.users) == 3
    assert not user_can_be_archived(active_user)


def test_check_password_for_blocked_user(
    sample_user,
):
    not_blocked_user = sample_user(blocked=True)
    assert not not_blocked_user.check_password('password')


def test_check_password_for_allowed_user(
    sample_user,
):
    allowed_user = sample_user(blocked=False)
    assert allowed_user.check_password('password')


def test_get_user_by_identity_provider_user_id(
    sample_user,
):
    user = sample_user(identity_provider_user_id='id-user-1')
    user_from_db = get_user_by_identity_provider_user_id(user.identity_provider_user_id)
    assert user == user_from_db
