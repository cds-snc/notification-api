from app import db
from app.models import InvitedUser
from datetime import datetime, timedelta
from sqlalchemy import select, delete


def save_invited_user(invited_user):
    if isinstance(invited_user, dict):
        invited_user_instance = InvitedUser(**invited_user)
    elif isinstance(invited_user, InvitedUser):
        invited_user_instance = invited_user
    else:
        raise TypeError(f'invited_user is of type {type(invited_user)}.')

    db.session.add(invited_user_instance)
    db.session.commit()
    return invited_user_instance


def get_invited_user(
    service_id,
    invited_user_id,
):
    stmt = select(InvitedUser).where(InvitedUser.service_id == service_id, InvitedUser.id == invited_user_id)
    return db.session.scalars(stmt).one()


def get_invited_user_by_id(invited_user_id):
    stmt = select(InvitedUser).where(InvitedUser.id == invited_user_id)
    return db.session.scalars(stmt).one()


def get_invited_users_for_service(service_id):
    stmt = select(InvitedUser).where(InvitedUser.service_id == service_id)
    return db.session.scalars(stmt).all()


def delete_invitations_created_more_than_two_days_ago():
    stmt = delete(InvitedUser).where(InvitedUser.created_at <= datetime.utcnow() - timedelta(days=2))
    deleted = db.session.execute(stmt).rowcount
    db.session.commit()
    return deleted
