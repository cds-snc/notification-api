from datetime import datetime, timedelta

from random import SystemRandom
from sqlalchemy import delete, func, select

from app import db
from app.models import VerifyCode
from app.model import User


def create_secret_code():
    return ''.join(map(str, [SystemRandom().randrange(10) for i in range(5)]))


def get_user_code(
    user,
    code,
    code_type,
) -> VerifyCode | None:
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


def get_user_by_id(user_id=None):
    if user_id is None:
        # Get all users.
        return db.session.scalars(select(User)).all()

    # Get one user, or raise an exception.
    stmt = select(User).where(User.id == user_id)
    return db.session.scalars(stmt).one()


def get_user_by_identity_provider_user_id(identity_provider_user_id):
    stmt = select(User).where(func.lower(User.identity_provider_user_id) == identity_provider_user_id.lower())

    return db.session.scalars(stmt).one()


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
