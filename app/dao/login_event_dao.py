from app import db

from app.dao.dao_utils import transactional


@transactional
def save_login_event(login_event):
    db.session.add(login_event)
