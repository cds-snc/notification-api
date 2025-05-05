"""Used by the scheduled Celery task: delete-invitations."""

from app import db
from app.models import InvitedUser
from datetime import datetime, timedelta
from sqlalchemy import delete


def delete_invitations_created_more_than_two_days_ago():
    stmt = delete(InvitedUser).where(InvitedUser.created_at <= datetime.utcnow() - timedelta(days=2))
    deleted = db.session.execute(stmt).rowcount
    db.session.commit()
    return deleted
