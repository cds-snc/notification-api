import pytest
import uuid
from app.dao.service_user_dao import dao_get_service_user, dao_update_service_user
from app.dao.users_dao import (
    save_model_user,
    save_user_attribute,
    get_user_by_id,
    delete_model_user,
    increment_failed_login_count,
    reset_failed_login_count,
    get_user_by_email,
    delete_codes_older_created_more_than_a_day_ago,
    update_user_password,
    create_secret_code,
    user_can_be_archived,
    dao_archive_user,
    get_user_by_identity_provider_user_id,
    update_user_identity_provider_user_id,
    create_or_retrieve_user,
    retrieve_match_or_create_user,
)
from app.errors import InvalidRequest
from app.model import User, EMAIL_AUTH_TYPE
from app.models import SMS_TYPE, VerifyCode
from app.oauth.exceptions import IdpAssignmentException, IncorrectGithubIdException
from datetime import datetime, timedelta
from freezegun import freeze_time
from sqlalchemy import or_, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm.exc import NoResultFound
from tests.app.db import create_permissions, create_template_folder


@pytest.fixture
def test_email():
    return f'{uuid.uuid4()}y@notifications.va.gov'


@pytest.fixture
def test_name():
    return f'Test User {uuid.uuid4()}'


@pytest.mark.serial  # Ensures only one user in the database
def test_create_only_one_user(
    test_name,
    test_email,
    notify_db_session,
):
    data = {'name': test_name, 'email_address': test_email, 'password': 'password'}

    user = User(**data)
    save_model_user(user)
    users = notify_db_session.session.scalars(select(User)).all()

    assert len(users) == 1

    # Teardown
    if user:
        notify_db_session.session.delete(user)
        notify_db_session.session.commit()


@pytest.mark.parametrize(
    'phone_number',
    [
        '+447700900986',
        '+1-800-555-5555',
    ],
)
def test_create_user(
    notify_db_session,
    phone_number,
    test_name,
    test_email,
):
    data = {'name': test_name, 'email_address': test_email, 'password': 'password', 'mobile_number': phone_number}

    user = User(**data)
    save_model_user(user)
    user_from_db = notify_db_session.session.get(User, user.id)

    assert not user.platform_admin
    assert user_from_db.email_address == data['email_address']
    assert user_from_db.id == user.id
    assert user_from_db.mobile_number == phone_number
    assert user_from_db.identity_provider_user_id is None
    assert len(user_from_db.idp_ids) == 0

    # Teardown
    if user:
        notify_db_session.session.delete(user)
        notify_db_session.session.commit()


def test_create_user_with_identity_provider_stores_github_idp_id(
    notify_db_session,
    test_name,
    test_email,
):
    identity_provider_user_id = 'test-user-id'
    data = {'name': test_name, 'email_address': test_email, 'identity_provider_user_id': identity_provider_user_id}
    user = User(**data)
    save_model_user(user)
    user_from_db = notify_db_session.session.get(User, user.id)

    assert not user.platform_admin
    assert user_from_db.email_address == test_email
    assert user_from_db.id == user.id
    assert user_from_db.identity_provider_user_id == identity_provider_user_id

    assert len(user_from_db.idp_ids) == 1
    idp_id = user_from_db.idp_ids[0]
    assert idp_id.user_id == user.id
    assert idp_id.idp_name == 'github'
    assert idp_id.idp_id == identity_provider_user_id

    # Teardown
    if user:
        notify_db_session.session.delete(user)
        notify_db_session.session.commit()


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


def test_create_user_fails_when_violates_sms_auth_requires_mobile_number_constraint(
    notify_db_session,
    test_email,
    test_name,
):
    data = {'name': test_name, 'email_address': test_email, 'auth_type': 'sms_auth'}

    with pytest.raises(IntegrityError):
        user = User(**data)
        save_model_user(user)


@pytest.mark.serial
def test_get_all_users(
    notify_db_session,
    sample_user,
    test_email,
):
    sample_user(email=test_email)
    sample_user(email=f'get_all{test_email}')

    assert len(notify_db_session.session.scalars(select(User)).all()) == 2
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


def test_increment_failed_login_should_increment_failed_logins(
    sample_user,
):
    user = sample_user()

    assert user.failed_login_count == 0
    increment_failed_login_count(user)
    assert user.failed_login_count == 1


def test_reset_failed_login_should_set_failed_logins_to_0(
    sample_user,
):
    user = sample_user()
    increment_failed_login_count(user)
    assert user.failed_login_count == 1
    reset_failed_login_count(user)
    assert user.failed_login_count == 0


def test_get_user_by_email(
    sample_user,
):
    user = sample_user()
    user_from_db = get_user_by_email(user.email_address)
    assert user == user_from_db


def test_get_user_by_email_is_case_insensitive(
    sample_user,
):
    user = sample_user()
    email = user.email_address
    user_from_db = get_user_by_email(email.upper())
    assert user == user_from_db


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


def test_update_user_attribute_blocked(
    sample_user,
):
    user = sample_user(mobile_number='+4407700900460')
    assert user.current_session_id is None
    save_user_attribute(user, {'blocked': True, 'mobile_number': '+2407700900460'})
    assert str(getattr(user, 'current_session_id')) == '00000000-0000-0000-0000-000000000000'


def test_update_user_password(
    sample_user,
):
    user = sample_user()
    password = 'newpassword'

    assert not user.check_password(password)
    update_user_password(user, password)
    assert user.check_password(password)


def test_create_secret_code_different_subsequent_codes():
    code1 = create_secret_code()
    code2 = create_secret_code()
    assert code1 != code2


def test_create_secret_code_returns_5_digits():
    code = create_secret_code()
    assert len(str(code)) == 5


@freeze_time('2018-07-07 12:00:00')
def test_dao_archive_user(
    sample_user,
    sample_organisation,
    sample_service,
    fake_uuid_v2,
):
    user = sample_user()
    user_original_email = user.email_address
    user.current_session_id = fake_uuid_v2

    # create 2 services for user to be a member of (each with another active user)
    service_1 = sample_service(service_name='Service 1')
    service_1_user = sample_user()
    service_1.users = [user, service_1_user]
    create_permissions(user, service_1, 'manage_settings')
    create_permissions(service_1_user, service_1, 'manage_settings', 'view_activity')

    service_2 = sample_service(service_name='Service 2')
    service_2_user = sample_user()
    service_2.users = [user, service_2_user]
    create_permissions(user, service_2, 'view_activity')
    create_permissions(service_2_user, service_2, 'manage_settings')

    # make user an org member
    sample_organisation.users = [user]

    # give user folder permissions for a service_1 folder
    folder = create_template_folder(service_1)
    service_user = dao_get_service_user(user.id, service_1.id)
    service_user.folders = [folder]
    dao_update_service_user(service_user)

    dao_archive_user(user)

    assert user.get_permissions() == {}
    assert user.services == []
    assert user.organisations == []
    assert user.auth_type == EMAIL_AUTH_TYPE
    assert user.email_address == f'_archived_2018-07-07_{user_original_email}'
    assert user.mobile_number is None
    assert user.current_session_id == uuid.UUID('00000000-0000-0000-0000-000000000000')
    assert user.state == 'inactive'
    assert not user.check_password('password')


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


def test_dao_archive_user_raises_error_if_user_cannot_be_archived(
    sample_user,
    mocker,
):
    mocker.patch('app.dao.users_dao.user_can_be_archived', return_value=False)

    with pytest.raises(InvalidRequest):
        dao_archive_user(sample_user().id)


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


@pytest.mark.parametrize(
    'initial_id_provider, expected_id_provider',
    [
        (None, 'test-id'),
        ('old-id', 'old-id'),
    ],
)
def test_update_user_identity_provider_user_id_for_identity_provider_when_none(
    initial_id_provider,
    expected_id_provider,
    sample_user,
):
    user = sample_user(identity_provider_user_id=initial_id_provider)

    user_from_db = update_user_identity_provider_user_id(user.email_address, expected_id_provider)

    assert user_from_db.identity_provider_user_id == expected_id_provider
    assert user_from_db.idp_ids[0].idp_name == 'github'
    assert user_from_db.idp_ids[0].idp_id == expected_id_provider


@pytest.mark.parametrize(
    'new_email',
    [
        True,
        False,
    ],
)
def test_update_user_identity_provider_user_id_do_not_update_email(
    new_email,
    fake_uuid_v2,
    sample_user,
):
    user = sample_user(identity_provider_user_id=fake_uuid_v2)
    email_address = f'new.{user.email_address}' if new_email else user.email_address
    user_from_db = update_user_identity_provider_user_id(email_address, fake_uuid_v2)
    assert user_from_db.email_address == user.email_address


def test_update_user_identity_provider_user_id_throws_exception_if_github_id_does_not_match(
    sample_user,
    test_email,
):
    sample_user(email=test_email, identity_provider_user_id='1111')

    with pytest.raises(IncorrectGithubIdException):
        update_user_identity_provider_user_id(test_email, '2222')


def test_create_or_retrieve_user_by_identity_provider_user_id_for_new_user(
    notify_db_session,
    sample_user,
    test_email,
    test_name,
    fake_uuid_v2,
):
    user = sample_user()
    created_user = create_or_retrieve_user(
        test_email,
        fake_uuid_v2,
        test_name,
    )

    assert user.id != created_user.id

    # Teardown - retrieve_match_or_create_user leaves artifacts
    if created_user:
        notify_db_session.session.delete(created_user)
        notify_db_session.session.commit()


def test_create_or_update_user_by_identity_provider_user_id_for_existing_user(
    notify_db_session,
    sample_user,
):
    user = sample_user()
    assert user.identity_provider_user_id is None
    name = str(uuid.uuid4())

    retrieved_user = create_or_retrieve_user(
        user.email_address,
        name,
        user.name,
    )

    assert user.identity_provider_user_id == name
    assert user.idp_ids[0].idp_name == 'github'
    assert user.idp_ids[0].idp_id == name
    # Ensure it retrieved rather than created
    assert user == notify_db_session.session.get(User, retrieved_user.id)


class TestRetrieveMatchCreateUsedForSSO:
    def test_should_match_by_email_and_assign_other_idp(
        self,
        notify_db_session,
        sample_user,
    ):
        user = sample_user()
        user.add_idp(idp_name='github', idp_id='some-id')
        user.save_to_db()
        created_user = retrieve_match_or_create_user(
            email_address=user.email_address,
            name='does not matter',
            identity_provider='va_sso',
            identity_provider_user_id='other-id',
        )

        assert created_user.id == user.id
        assert len(created_user.idp_ids) == 2

        # Teardown - retrieve_match_or_create_user leaves artifacts
        if created_user:
            notify_db_session.session.delete(created_user)
            notify_db_session.session.commit()

    def test_raises_exception_when_user_has_conflicting_idp_id(
        self,
        notify_db_session,
        sample_user,
    ):
        user = sample_user()
        user.add_idp(idp_name='va_sso', idp_id='some-id')
        user.save_to_db()

        with pytest.raises(IdpAssignmentException):
            retrieve_match_or_create_user(
                email_address=user.email_address,
                name='does not matter',
                identity_provider='va_sso',
                identity_provider_user_id='other-id',
            )

        db_user = notify_db_session.session.get(User, user.id)
        assert db_user.idp_ids[0].idp_id == 'some-id'
