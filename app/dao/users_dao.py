from datetime import datetime, timedelta
from typing import Optional
import uuid

from flask import current_app
from random import SystemRandom
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import FlushError, NoResultFound
from sqlalchemy.exc import IntegrityError

from app import db
from app.constants import EMAIL_AUTH_TYPE
from app.dao.permissions_dao import permission_dao
from app.dao.service_user_dao import dao_get_service_users_by_user_id
from app.dao.dao_utils import transactional
from app.errors import InvalidRequest
from app.models import VerifyCode
from app.model import User
from app.oauth.exceptions import IdpAssignmentException, IncorrectGithubIdException
from app.utils import escape_special_characters


def _remove_values_for_keys_if_present(
    dict,
    keys,
):
    for key in keys:
        dict.pop(key, None)


def create_secret_code():
    return ''.join(map(str, [SystemRandom().randrange(10) for i in range(5)]))


def save_user_attribute(
    usr,
    update_dict,
):
    # Check that it is there AND not empty
    if update_dict.get('blocked'):
        update_dict.update({'current_session_id': '00000000-0000-0000-0000-000000000000'})

    stmt = update(User).where(User.id == usr.id).values(update_dict)
    db.session.execute(stmt)
    db.session.commit()


def save_model_user(
    usr,
    pwd=None,
):
    if pwd:
        usr.password = pwd
        usr.password_changed_at = datetime.utcnow()

    db.session.add(usr)
    db.session.commit()


def create_user_code(
    user,
    code,
    code_type,
):
    verify_code = VerifyCode(code_type=code_type, expiry_datetime=datetime.utcnow() + timedelta(minutes=30), user=user)
    verify_code.code = code
    db.session.add(verify_code)
    db.session.commit()
    return verify_code


def get_user_code(
    user,
    code,
    code_type,
) -> Optional[VerifyCode]:
    """
    Get the most recent codes to try and reduce the time searching for the correct code.
    """

    stmt = (
        select(VerifyCode)
        .where(VerifyCode.user == user, VerifyCode.code_type == code_type)
        .order_by(VerifyCode.created_at.desc())
    )

    for verify_code in db.session.scalars(stmt).all():
        if verify_code.check_code(code):
            return verify_code

    return None


def delete_codes_older_created_more_than_a_day_ago() -> int:
    stmt = delete(VerifyCode).where(VerifyCode.created_at < datetime.utcnow() - timedelta(hours=24))
    rows_deleted = db.session.execute(stmt).rowcount
    db.session.commit()
    return rows_deleted


def use_user_code(verify_code_id):
    verify_code = db.session.get(VerifyCode, verify_code_id)
    verify_code.code_used = True
    db.session.add(verify_code)
    db.session.commit()


def delete_model_user(user):
    db.session.delete(user)
    db.session.commit()


def delete_user_verify_codes(user) -> int:
    stmt = delete(VerifyCode).where(VerifyCode.user == user)
    db.session.execute(stmt)
    db.session.commit()


def count_user_verify_codes(user) -> int:
    stmt = (
        select(func.count())
        .select_from(VerifyCode)
        .where(VerifyCode.user == user, VerifyCode.expiry_datetime > datetime.utcnow(), VerifyCode.code_used.is_(False))
    )

    return db.session.scalar(stmt)


def verify_within_time(
    user,
    age=timedelta(seconds=30),
):
    stmt = (
        select(func.count())
        .select_from(VerifyCode)
        .where(
            VerifyCode.user == user, VerifyCode.code_used.is_(False), VerifyCode.created_at > (datetime.utcnow() - age)
        )
    )

    return db.session.scalar(stmt)


def get_user_by_id(user_id=None):
    if user_id is None:
        # Get all users.
        return db.session.scalars(select(User)).all()

    # Get one user, or raise an exception.
    stmt = select(User).where(User.id == user_id)
    return db.session.scalars(stmt).one()


def get_user_by_email(email):
    stmt = select(User).where(func.lower(User.email_address) == email.lower())
    return db.session.scalars(stmt).one()


def get_users_by_partial_email(email):
    email = escape_special_characters(email)
    stmt = select(User).where(User.email_address.ilike(f'%{email}%'))
    return db.session.scalars(stmt).all()


def get_user_by_identity_provider_user_id(identity_provider_user_id):
    stmt = select(User).where(func.lower(User.identity_provider_user_id) == identity_provider_user_id.lower())

    return db.session.scalars(stmt).one()


@transactional
def update_user_identity_provider_user_id(
    email,
    identity_provider_user_id,
):
    email_matches_condition = func.lower(User.email_address) == func.lower(email)
    id_matches_condition = func.lower(User.identity_provider_user_id) == func.lower(str(identity_provider_user_id))
    stmt = select(User).where(or_(email_matches_condition, id_matches_condition))
    user = db.session.scalars(stmt).one()

    if user.identity_provider_user_id is None:
        current_app.logger.info(
            f'User {user.id} matched by email. Creating account with '
            f'identity provider user id {user.identity_provider_user_id}'
        )
        user.identity_provider_user_id = identity_provider_user_id
        db.session.add(user)
    else:
        if str(user.identity_provider_user_id) != str(identity_provider_user_id):
            raise IncorrectGithubIdException(
                f'User {user.id}: identity provider user id on user ({user.identity_provider_user_id})'
                f' does not match id received from Github ({identity_provider_user_id})'
            )

        current_app.logger.info(f'User {user.id} matched by identity provider user id {user.identity_provider_user_id}')

    return user


def create_or_retrieve_user(
    email_address,
    identity_provider_user_id,
    name,
):
    try:
        return update_user_identity_provider_user_id(email_address, identity_provider_user_id)
    except NoResultFound:
        data = {'email_address': email_address, 'identity_provider_user_id': identity_provider_user_id, 'name': name}
        user = User(**data)
        save_model_user(user)

        return user


@transactional
def retrieve_match_or_create_user(
    email_address: str, name: str, identity_provider: str, identity_provider_user_id: str
) -> User:
    try:
        user = User.find_by_idp(identity_provider, identity_provider_user_id)
        return user
    except NoResultFound:
        try:
            user = get_user_by_email(email_address)
            user.add_idp(idp_name=identity_provider, idp_id=identity_provider_user_id)
            user.save_to_db()
            return user
        except (IntegrityError, FlushError) as e:
            raise IdpAssignmentException from e
        except NoResultFound:
            user = User(
                idp_name=identity_provider, idp_id=identity_provider_user_id, name=name, email_address=email_address
            )
            user.save_to_db()
            return user


def increment_failed_login_count(user):
    user.failed_login_count += 1
    db.session.add(user)
    db.session.commit()


def reset_failed_login_count(user):
    if user.failed_login_count > 0:
        user.failed_login_count = 0
        db.session.add(user)
        db.session.commit()


def update_user_password(
    user,
    password,
):
    # reset failed login count - they've just reset their password so should be fine
    user.password = password
    user.password_changed_at = datetime.utcnow()
    db.session.add(user)
    db.session.commit()


def get_user_and_accounts(user_id):
    stmt = (
        select(User)
        .options(
            # eagerly load the user's services and organisations, and also the service's org and vice versa
            # (so we can see if the user knows about it)
            joinedload('services'),
            joinedload('organisations'),
            joinedload('organisations.services'),
            joinedload('services.organisation'),
        )
        .where(User.id == user_id)
    )

    return db.session.scalars(stmt).unique().one()


@transactional
def dao_archive_user(user):
    if not user_can_be_archived(user):
        msg = 'User can’t be removed from a service - check all services have another team member with manage_settings'
        raise InvalidRequest(msg, 400)

    permission_dao.remove_user_service_permissions_for_all_services(user)

    service_users = dao_get_service_users_by_user_id(user.id)
    for service_user in service_users:
        db.session.delete(service_user)

    user.organisations = []

    user.auth_type = EMAIL_AUTH_TYPE
    user.email_address = get_archived_email_address(user.email_address)
    user.mobile_number = None
    user.password = str(uuid.uuid4())
    # Changing the current_session_id signs the user out
    user.current_session_id = '00000000-0000-0000-0000-000000000000'
    user.state = 'inactive'

    db.session.add(user)


def user_can_be_archived(user):
    active_services = [x for x in user.services if x.active]

    for service in active_services:
        other_active_users = [x for x in service.users if x.state == 'active' and x != user]

        if not other_active_users:
            return False

        if not any('manage_settings' in user.get_permissions(service.id) for user in other_active_users):
            # no-one else has manage settings
            return False

    return True


def get_archived_email_address(email_address):
    date = datetime.utcnow().strftime('%Y-%m-%d')
    return '_archived_{}_{}'.format(date, email_address)
