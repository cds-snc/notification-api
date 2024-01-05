from datetime import datetime, timedelta
from app import db

from app.models import InvitedOrganisationUser
from sqlalchemy import select, delete


def save_invited_org_user(invited_org_user):
    db.session.add(invited_org_user)
    db.session.commit()


def get_invited_org_user(organisation_id, invited_org_user_id):
    stmt = select(InvitedOrganisationUser).where(
        InvitedOrganisationUser.organisation_id == organisation_id,
        InvitedOrganisationUser.id == invited_org_user_id
    )
    return db.session.scalars(stmt).one()


def get_invited_org_user_by_id(invited_org_user_id):
    stmt = select(InvitedOrganisationUser).where(
        InvitedOrganisationUser.id == invited_org_user_id
    )
    return db.session.scalars(stmt).one()


def get_invited_org_users_for_organisation(organisation_id):
    stmt = select(InvitedOrganisationUser).where(
        InvitedOrganisationUser.organisation_id == organisation_id
    )
    return db.session.scalars(stmt).all()


def delete_org_invitations_created_more_than_two_days_ago():
    stmt = delete(InvitedOrganisationUser).where(
        InvitedOrganisationUser.created_at <= datetime.utcnow() - timedelta(days=2)
    )
    deleted = db.session.execute(stmt).rowcount
    db.session.commit()
    return deleted
