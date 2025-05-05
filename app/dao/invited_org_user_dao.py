from datetime import datetime, timedelta
from app import db

from app.models import InvitedOrganisationUser
from sqlalchemy import delete


def delete_org_invitations_created_more_than_two_days_ago():
    # Used in a scheduled Celery task: delete-invitations
    stmt = delete(InvitedOrganisationUser).where(
        InvitedOrganisationUser.created_at <= datetime.utcnow() - timedelta(days=2)
    )
    deleted = db.session.execute(stmt).rowcount
    db.session.commit()
    return deleted
