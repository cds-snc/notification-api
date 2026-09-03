from sqlalchemy import delete

from app import db
from app.cache.cache_events import cache_invalidating_dml
from app.dao.dao_utils import transactional
from app.models import ServicePermission


def dao_fetch_service_permissions(service_id):
    return ServicePermission.query.filter(ServicePermission.service_id == service_id).all()


@transactional
def dao_add_service_permission(service_id, permission):
    service_permission = ServicePermission(service_id=service_id, permission=permission)
    db.session.add(service_permission)


def dao_remove_service_permission(service_id, permission):
    statement = delete(ServicePermission).where(
        ServicePermission.service_id == service_id,
        ServicePermission.permission == permission,
    )
    result = db.session.execute(cache_invalidating_dml(statement, service_id=service_id))

    db.session.commit()
    return result.rowcount
