from app import db
from app.models import LoginEvent

from app.dao.dao_utils import (
    transactional
)


def list_login_events(user_id):
    return LoginEvent.query.filter(
        LoginEvent.user_id == user_id
    ).order_by(LoginEvent.created_at.desc()).limit(3).all()


@transactional
def save_login_event(login_event):
    return db.session.add(login_event)
