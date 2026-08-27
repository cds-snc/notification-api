"""Service cache invalidation hooks driven by SQLAlchemy ORM session events.

These listeners collect service IDs touched during a transaction and invalidate
service-related dogpile cache keys only after the transaction commits.

Why this pattern:
- We avoid stale cache reads after successful writes.
- We avoid invalidating cache for rolled-back transactions.
- We centralize invalidation so individual write paths do not each need to call
    cache invalidation manually.
"""

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.caching import invalidate_service_cache_keys
from app.models import Service, ServicePermission, ServiceUser

_SERVICE_CACHE_IDS_KEY = "service_cache_ids_to_invalidate"
_EVENTS_REGISTERED = False


def _collect_service_ids_from_instances(session, flush_context):
    """Collect service IDs affected by this flush into session-local state.

    SQLAlchemy calls this after pending ORM changes are flushed to SQL. We do
    not invalidate here because the transaction can still roll back.

    The collected IDs are stored in ``session.info`` and consumed in
    ``_invalidate_service_cache_after_commit``.
    """
    service_ids = session.info.setdefault(_SERVICE_CACHE_IDS_KEY, set())

    for instance in session.new.union(session.dirty).union(session.deleted):
        if isinstance(instance, Service):
            if instance.id:
                service_ids.add(str(instance.id))
            continue

        if isinstance(instance, (ServicePermission, ServiceUser)):
            if instance.service_id:
                service_ids.add(str(instance.service_id))
            continue


def _invalidate_service_cache_after_commit(session):
    """Invalidate cached service payloads for all IDs touched in this transaction.

    This runs only after a successful commit, ensuring cache accurately reflects DB state.
    """
    service_ids = session.info.pop(_SERVICE_CACHE_IDS_KEY, set())
    for service_id in service_ids:
        invalidate_service_cache_keys(service_id)


def _clear_service_cache_ids_after_rollback(session):
    """Discard collected service IDs when a transaction is rolled back."""
    session.info.pop(_SERVICE_CACHE_IDS_KEY, None)


def register_service_cache_orm_events():
    """Register service-cache session listeners once per process.

    Registration is idempotent and guarded by `_EVENTS_REGISTERED` so app
    startup paths and tests can safely call this multiple times.
    """
    global _EVENTS_REGISTERED

    if _EVENTS_REGISTERED:
        return

    event.listen(Session, "after_flush", _collect_service_ids_from_instances)
    event.listen(Session, "after_commit", _invalidate_service_cache_after_commit)
    event.listen(Session, "after_rollback", _clear_service_cache_ids_after_rollback)

    _EVENTS_REGISTERED = True
