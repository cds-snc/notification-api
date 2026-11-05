"""Declarative mappings from ORM model changes to cache groups."""

from dataclasses import dataclass

from app.models import (
    Notification,
    Permission,
    Service,
    ServicePermission,
    ServiceUser,
    Template,
    TemplateRedacted,
    User,
)


@dataclass(frozen=True)
class CacheInvalidationRule:
    """Describe how an ORM model change maps to a cache group."""

    namespace: str
    entity_id_attribute: str
    # Skip invalidation for newly inserted rows when a cache entry cannot exist yet
    # (e.g. misses are never cached), avoiding a Redis round trip on hot insert paths.
    invalidate_on_insert: bool = True


CACHE_INVALIDATION_REGISTRY = {
    Notification: [
        CacheInvalidationRule(namespace="notification", entity_id_attribute="id", invalidate_on_insert=False),
    ],
    Service: [
        CacheInvalidationRule(namespace="service", entity_id_attribute="id"),
    ],
    ServicePermission: [
        CacheInvalidationRule(namespace="service", entity_id_attribute="service_id"),
    ],
    ServiceUser: [
        CacheInvalidationRule(namespace="service", entity_id_attribute="service_id"),
        CacheInvalidationRule(namespace="user", entity_id_attribute="user_id"),
    ],
    User: [
        CacheInvalidationRule(namespace="user", entity_id_attribute="id"),
    ],
    Permission: [
        CacheInvalidationRule(namespace="user", entity_id_attribute="user_id"),
    ],
    Template: [
        CacheInvalidationRule(namespace="template", entity_id_attribute="id"),
    ],
    TemplateRedacted: [
        CacheInvalidationRule(namespace="template", entity_id_attribute="template_id"),
    ],
}
