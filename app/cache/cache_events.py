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
_CACHE_INVALIDATION_ENTITY_IDS_OPTION = "cache_invalidation_entity_ids"
_EVENTS_REGISTERED = False


def cache_invalidating_dml(statement, **entity_ids):
    """Attach entity IDs for registry-driven invalidation of ORM bulk DML."""
    return statement.execution_options(**{_CACHE_INVALIDATION_ENTITY_IDS_OPTION: entity_ids})


def _as_entity_id_collection(value):
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return value
    return (value,)


def _queue_cache_invalidation(session, namespace, entity_id):
    session.info.setdefault(_CACHE_INVALIDATIONS_KEY, set()).add((namespace, str(entity_id)))


def _queue_model_invalidations(session, model, entity_ids):
    rules = CACHE_INVALIDATION_REGISTRY.get(model, ())
    required_attributes = {rule.entity_id_attribute for rule in rules}
    missing_attributes = required_attributes.difference(entity_ids)
    if missing_attributes:
        missing = ", ".join(sorted(missing_attributes))
        raise ValueError(f"Missing cache invalidation entity IDs for {model.__name__}: {missing}")

    for rule in rules:
        for entity_id in _as_entity_id_collection(entity_ids.get(rule.entity_id_attribute)):
            _queue_cache_invalidation(session, rule.namespace, entity_id)


def _collect_cache_invalidations(session, flush_context):
    """Resolve changed ORM instances to cache groups and collect them.

    SQLAlchemy calls this after pending ORM changes are flushed to SQL. We do
    not invalidate here because the transaction can still roll back.

    Targets are stored as ``(namespace, entity_id)`` tuples in ``session.info``.
    The set deduplicates cases where several changed rows affect the same cache
    group in one transaction.
    """
    for instance in session.new.union(session.dirty).union(session.deleted):
        for model, rules in CACHE_INVALIDATION_REGISTRY.items():
            if not isinstance(instance, model):
                continue

            for rule in rules:
                entity_id = getattr(instance, rule.entity_id_attribute, None)
                if entity_id is not None:
                    _queue_cache_invalidation(session, rule.namespace, entity_id)


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


def _intercept_bulk_operations(orm_context):
    if not (orm_context.is_delete or orm_context.is_update):
        return

    mapper = orm_context.bind_mapper
    if mapper is None:
        return

    entity_ids = orm_context.execution_options.get(_CACHE_INVALIDATION_ENTITY_IDS_OPTION)
    if entity_ids:
        _queue_model_invalidations(orm_context.session, mapper.class_, entity_ids)


def register_cache_orm_events():
    """Register registry-driven cache listeners once per process."""
    global _EVENTS_REGISTERED

    if _EVENTS_REGISTERED:
        return

    event.listen(Session, "after_flush", _collect_cache_invalidations)
    event.listen(Session, "after_commit", _invalidate_cache_after_commit)
    event.listen(Session, "after_rollback", _clear_cache_invalidations_after_rollback)
    event.listen(Session, "do_orm_execute", _intercept_bulk_operations)

    _EVENTS_REGISTERED = True