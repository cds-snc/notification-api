import uuid
from datetime import datetime, timedelta
from random import SystemRandom

import pytz
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app import db
from app.dao.dao_utils import transactional
from app.dao.permissions_dao import permission_dao
from app.dao.service_user_dao import dao_get_service_users_by_user_id
from app.errors import InvalidRequest
from app.history_meta import create_history
from app.models import EMAIL_AUTH_TYPE, Service, ServiceUser, User, VerifyCode
from app.utils import escape_special_characters


def _remove_values_for_keys_if_present(dict, keys):
    for key in keys:
        dict.pop(key, None)


def create_secret_code():
    return "".join(map(str, [SystemRandom().randrange(10) for i in range(5)]))


def save_user_attribute(usr: User, update_dict={}):
    if "blocked" in update_dict and update_dict["blocked"]:
        update_dict.update({"current_session_id": "00000000-0000-0000-0000-000000000000"})

    db.session.query(User).filter_by(id=usr.id).update(update_dict)
    db.session.commit()


def save_model_user(usr: User, update_dict={}, pwd=None):
    if pwd:
        usr.password = pwd
        usr.password_changed_at = datetime.utcnow()

    if update_dict:
        _remove_values_for_keys_if_present(update_dict, ["id", "password_changed_at"])
        db.session.query(User).filter_by(id=usr.id).update(update_dict)
    else:
        db.session.add(usr)
    db.session.commit()


def create_user_code(user, code, code_type):
    verify_code = VerifyCode(
        code_type=code_type,
        expiry_datetime=datetime.utcnow() + timedelta(minutes=30),
        user=user,
    )
    verify_code.code = code
    db.session.add(verify_code)
    db.session.commit()
    return verify_code


def get_user_code(user, code, code_type):
    # Get the most recent codes to try and reduce the
    # time searching for the correct code.
    codes = VerifyCode.query.filter_by(user=user, code_type=code_type).order_by(VerifyCode.created_at.desc())
    return next((x for x in codes if x.check_code(code)), None)


def delete_codes_older_created_more_than_a_day_ago():
    deleted = db.session.query(VerifyCode).filter(VerifyCode.created_at < datetime.utcnow() - timedelta(hours=24)).delete()
    db.session.commit()
    return deleted


def use_user_code(id):
    verify_code = VerifyCode.query.get(id)
    verify_code.code_used = True
    db.session.add(verify_code)
    db.session.commit()


def delete_model_user(user):
    db.session.delete(user)
    db.session.commit()


def delete_user_verify_codes(user):
    VerifyCode.query.filter_by(user=user).delete()
    db.session.commit()


def count_user_verify_codes(user):
    query = VerifyCode.query.filter(
        VerifyCode.user == user,
        VerifyCode.expiry_datetime > datetime.utcnow(),
        VerifyCode.code_used.is_(False),
    )
    return query.count()


def verify_within_time(user, age=timedelta(seconds=30)):
    query = VerifyCode.query.filter(
        VerifyCode.user == user,
        VerifyCode.code_used.is_(False),
        VerifyCode.created_at > (datetime.utcnow() - age),
    )
    return query.count()


def get_user_by_id(user_id=None) -> User:
    if user_id:
        return User.query.filter_by(id=user_id).one()
    return User.query.filter_by().all()


def get_user_by_email(email):
    return User.query.filter(func.lower(User.email_address) == func.lower(email)).one()


def get_users_by_partial_email(email):
    email = escape_special_characters(email)
    return User.query.filter(User.email_address.ilike("%{}%".format(email))).all()


def increment_failed_login_count(user):
    user.failed_login_count += 1
    db.session.add(user)
    db.session.commit()


def reset_failed_login_count(user):
    if user.failed_login_count > 0:
        user.failed_login_count = 0
        db.session.add(user)
        db.session.commit()


def update_user_password(user, password):
    # reset failed login count - they've just reset their password so should be fine
    user.password = password
    user.password_changed_at = datetime.utcnow()
    user.password_expired = False
    db.session.add(user)
    db.session.commit()


def get_user_and_accounts(user_id):
    return (
        User.query.filter(User.id == user_id)
        .options(
            # eagerly load the user's services and organisations, and also the service's org and vice versa
            # (so we can see if the user knows about it)
            joinedload("services"),
            joinedload("organisations"),
            joinedload("organisations.services"),
            joinedload("services.organisation"),
        )
        .one()
    )


@transactional
def dao_archive_user(user):
    if not user_can_be_archived(user):
        msg = "User cannot be removed from service. " "Check that all services have another team member who can manage settings"
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
    user.current_session_id = "00000000-0000-0000-0000-000000000000"
    user.state = "inactive"

    db.session.add(user)


def user_can_be_archived(user):
    active_services = [x for x in user.services if x.active]

    for service in active_services:
        other_active_users = [x for x in service.users if x.state == "active" and x != user]

        if not other_active_users:
            return False

        if not any("manage_settings" in user.get_permissions(service.id) for user in other_active_users):
            # no-one else has manage settings
            return False

    return True


def get_archived_email_address(email_address):
    date = datetime.utcnow().strftime("%Y-%m-%d")
    return "_archived_{}_{}".format(date, email_address)


def get_services_for_all_users():
    """
    Return (user_id, email_address, [service_id1, service_id2]...] for all users
    where both the user and the service are active.

    """
    result = (
        db.session.query(
            User.id.label("user_id"),
            User.email_address.label("email_address"),
            func.array_agg(Service.id).label("service_ids"),
        )
        .join(ServiceUser, User.id == ServiceUser.user_id)
        .join(Service, Service.id == ServiceUser.service_id)
        .filter(User.state == "active", Service.active.is_(True), Service.restricted.is_(False), Service.research_mode.is_(False))
        .group_by(User.id, User.email_address)
        .all()
    )

    return result


@transactional
def dao_deactivate_user(user_id):
    """
    Deactivates a user by updating their state and removing associated permissions.
    """
    user = get_user_by_id(user_id)

    if user.state == "inactive":
        raise InvalidRequest("User is already inactive", status_code=400)

    # Remove user permissions and associations
    permission_dao.remove_user_service_permissions_for_all_services(user)

    service_users = dao_get_service_users_by_user_id(user.id)
    for service_user in service_users:
        db.session.delete(service_user)

    user.organisations = []

    user.auth_type = EMAIL_AUTH_TYPE
    user.mobile_number = None
    user.password = str(uuid.uuid4())
    # Changing the current_session_id signs the user out
    user.current_session_id = "00000000-0000-0000-0000-000000000000"
    user.state = "inactive"

    db.session.add(user)
    db.session.commit()

    return user


@transactional
def dao_deactivate_user_and_suspend_services(user_id):
    """
    Suspends any services that should be suspended because of this user's deactivation
    and then deactivates the user in a single transaction. This ensures that if
    anything fails during the process, changes are rolled back together.

    Returns (user, suspended_service_ids)
    """
    user = get_user_by_id(user_id)

    if user.state == "inactive":
        raise InvalidRequest("User is already inactive", status_code=400)

    suspended_service_ids = []

    # Determine services to suspend and update them in-session (no intermediate commit)
    for service in list(user.services):
        members = [member for member in service.users if member.state == "active"]
        service_is_live = not service.restricted

        if service.active:
            # Suspend live services with 2 or fewer members or trial services with only 1 member
            if (service_is_live and len(members) <= 2) or (not service_is_live and len(members) == 1):
                service.active = False
                service.suspended_at = datetime.utcnow().replace(tzinfo=pytz.UTC)
                service.suspended_by_id = user.id
                suspended_service_ids.append(service.id)
                # create history for the suspended service immediately to avoid session flush issues
                db.session.add(create_history(service))

    # Now deactivate the user (same logic as dao_deactivate_user)
    permission_dao.remove_user_service_permissions_for_all_services(user)

    service_users = dao_get_service_users_by_user_id(user.id)
    for service_user in service_users:
        db.session.delete(service_user)

    user.organisations = []

    user.auth_type = EMAIL_AUTH_TYPE
    user.mobile_number = None
    user.password = str(uuid.uuid4())
    # Changing the current_session_id signs the user out
    user.current_session_id = "00000000-0000-0000-0000-000000000000"
    user.state = "inactive"

    db.session.add(user)
    # Record history for the user as well, but only if the User model is versioned
    # (not all models have history mapping - create_history requires __history_mapper__)
    if hasattr(user, "__history_mapper__"):
        db.session.add(create_history(user))

    return user, suspended_service_ids
