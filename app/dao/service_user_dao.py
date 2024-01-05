
from app import db
from app.dao.dao_utils import transactional
from app.models import ServiceUser
from app.model import User
from sqlalchemy import select


def dao_get_service_user(user_id, service_id):
    stmt = select(ServiceUser).where(
        ServiceUser.user_id == user_id,
        ServiceUser.service_id == service_id
    )
    return db.session.scalars(stmt).one()


def dao_get_active_service_users(service_id):
    stmt = (
        select(ServiceUser)
        .join(User)
        .where(
            ServiceUser.service_id == service_id,
            User.state == 'active'
        )
    )
    return db.session.scalars(stmt).all()


def dao_get_service_users_by_user_id(user_id):
    stmt = select(ServiceUser).where(ServiceUser.user_id == user_id)
    return db.session.scalars(stmt).all()


@transactional
def dao_update_service_user(service_user):
    db.session.add(service_user)
