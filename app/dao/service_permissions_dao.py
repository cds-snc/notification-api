from app import db
from app.dao.dao_utils import transactional
from app.models import ServicePermission


def dao_fetch_service_permissions(service_id):
    return ServicePermission.query.filter(ServicePermission.service_id == service_id).all()


@transactional
def dao_add_service_permission(service_id, permission):
    service_permission = ServicePermission(service_id=service_id, permission=permission)
    db.session.add(service_permission)


def dao_remove_service_permission(service_id, permission):
    """Remove matching service permissions via ORM deletes.

    We intentionally delete loaded ORM objects instead of issuing a bulk
    ``query.delete()`` so SQLAlchemy session events can observe these changes.
    This allows service cache invalidation hooks to run consistently.
    """
    service_permissions = ServicePermission.query.filter(
        ServicePermission.service_id == service_id,
        ServicePermission.permission == permission,
    ).all()

    for service_permission in service_permissions:
        db.session.delete(service_permission)

    db.session.commit()
    return len(service_permissions)
