"""Registry-driven cache invalidation using SQLAlchemy ORM session events.

The listeners resolve changed ORM models through the invalidation registry,
collect affected cache groups during a flush, and delete their grouped dogpile
keys only after the transaction commits.
"""

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.cache.cache_invalidation_registry import CACHE_INVALIDATION_REGISTRY
from app.caching import invalidate_group_keys

_CACHE_INVALIDATIONS_KEY = "cache_invalidations_to_run"
_EVENTS_REGISTERED = False


def _collect_cache_invalidations(session, flush_context):
    """Resolve changed ORM instances to cache groups and collect them.

    SQLAlchemy calls this after pending ORM changes are flushed to SQL. We do
    not invalidate here because the transaction can still roll back.

    Targets are stored as ``(namespace, entity_id)`` tuples in ``session.info``.
    The set deduplicates cases where several changed rows affect the same cache
    group in one transaction.
    """
    invalidations = session.info.setdefault(_CACHE_INVALIDATIONS_KEY, set())

    for instance in session.new.union(session.dirty).union(session.deleted):
        for model, rules in CACHE_INVALIDATION_REGISTRY.items():
            if not isinstance(instance, model):
                continue

            for rule in rules:
                entity_id = getattr(instance, rule.entity_id_attribute, None)
                if entity_id is not None:
                    invalidations.add((rule.namespace, str(entity_id)))


def _invalidate_cache_after_commit(session):
    """Delete grouped cache keys affected by the committed transaction."""
    invalidations = session.info.pop(_CACHE_INVALIDATIONS_KEY, set())
    for namespace, entity_id in invalidations:
        try:
            invalidate_group_keys(namespace, entity_id)
        except Exception:
            pass


def _clear_cache_invalidations_after_rollback(session):
    """Discard collected invalidation targets after a rollback."""
    session.info.pop(_CACHE_INVALIDATIONS_KEY, None)


def register_cache_orm_events():
    """Register registry-driven cache listeners once per process."""
    global _EVENTS_REGISTERED

    if _EVENTS_REGISTERED:
        return

    event.listen(Session, "after_flush", _collect_cache_invalidations)
    event.listen(Session, "after_commit", _invalidate_cache_after_commit)
    event.listen(Session, "after_rollback", _clear_cache_invalidations_after_rollback)

    _EVENTS_REGISTERED = True