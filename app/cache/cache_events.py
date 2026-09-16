"""Registry-driven cache invalidation using SQLAlchemy ORM session events.

The listeners resolve changed ORM models through the invalidation registry,
collect affected cache groups during a flush, and delete their grouped dogpile
keys only after the transaction commits.
"""

import logging
from collections.abc import Iterator, Mapping
from threading import Lock
from typing import cast
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session
from sqlalchemy.orm.unitofwork import UOWTransaction

from app.cache.cache_dml import _CACHE_INVALIDATION_ENTITY_IDS_OPTION
from app.cache.cache_invalidation_registry import CACHE_INVALIDATION_REGISTRY
from app.caching import invalidate_group_keys

_CACHE_INVALIDATIONS_KEY = "cache_invalidations_to_run"
_EVENT_REGISTRATION_LOCK = Lock()
# ORM events are tied to a global sqlalchemy session which could exist outside of
# a flask context, so use a module level logger instead.
logger = logging.getLogger(__name__)

EntityId = UUID | str
EntityIdValue = (
    EntityId
    | list[EntityId]
    | tuple[EntityId, ...]
    | set[EntityId]
    | frozenset[EntityId]
    | None
)
EntityIds = Mapping[str, EntityIdValue]
CacheInvalidation = tuple[str, str]


def _as_entity_id_collection(value: EntityIdValue) -> Iterator[EntityId]:
    if value is None:
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        yield from value
    else:
        yield value


def _queue_cache_invalidation(session: Session, namespace: str, entity_id: EntityId) -> None:
    session.info.setdefault(_CACHE_INVALIDATIONS_KEY, set()).add(
        (namespace, str(entity_id))
    )


def _queue_entity_invalidations(
    session: Session, model: type[object], entity_ids: EntityIds
) -> None:
    rules = CACHE_INVALIDATION_REGISTRY.get(model, ())
    # Bulk operations bypass ORM instance tracking, so callers must provide every
    # ID used by the model's rules. For example, omitting user_id for ServiceUser
    # would invalidate the service cache while silently leaving the user cache stale.
    required_attributes = {rule.entity_id_attribute for rule in rules}
    missing_attributes = required_attributes.difference(entity_ids)
    if missing_attributes:
        missing = ", ".join(sorted(missing_attributes))
        raise ValueError(
            f"Missing cache invalidation entity IDs for {model.__name__}: {missing}"
        )

    for rule in rules:
        for entity_id in _as_entity_id_collection(
            entity_ids.get(rule.entity_id_attribute)
        ):
            _queue_cache_invalidation(session, rule.namespace, entity_id)


def _collect_cache_invalidations(
    session: Session, flush_context: UOWTransaction
) -> None:
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


def _invalidate_cache_after_commit(session: Session) -> None:
    """Delete grouped cache keys affected by the committed transaction."""
    invalidations: set[CacheInvalidation] = session.info.pop(
        _CACHE_INVALIDATIONS_KEY, set()
    )
    for namespace, entity_id in invalidations:
        try:
            invalidate_group_keys(namespace, entity_id)
        except Exception:
            logger.exception(
                "Failed to invalidate cache group",
                extra={
                    "cache_namespace": namespace,
                    "cache_entity_id": entity_id,
                },
            )


def _clear_cache_invalidations_after_rollback(session: Session) -> None:
    """Discard collected invalidation targets after a rollback."""
    session.info.pop(_CACHE_INVALIDATIONS_KEY, None)


def _intercept_bulk_operations(orm_context: ORMExecuteState) -> None:
    if not (orm_context.is_delete or orm_context.is_update):
        return

    mapper = orm_context.bind_mapper
    if mapper is None:
        return

    entity_ids = cast(
        EntityIds | None,
        orm_context.execution_options.get(_CACHE_INVALIDATION_ENTITY_IDS_OPTION),
    )
    if entity_ids:
        _queue_entity_invalidations(orm_context.session, mapper.class_, entity_ids)


def register_cache_orm_events() -> None:
    """Register registry-driven cache listeners once per process."""
    listeners = (
        ("after_flush", _collect_cache_invalidations),
        ("after_commit", _invalidate_cache_after_commit),
        ("after_rollback", _clear_cache_invalidations_after_rollback),
        ("do_orm_execute", _intercept_bulk_operations),
    )

    with _EVENT_REGISTRATION_LOCK:
        for event_name, listener in listeners:
            if not event.contains(Session, event_name, listener):
                event.listen(Session, event_name, listener)
