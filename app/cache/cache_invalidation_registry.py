"""Declarative mappings from ORM model changes to cache groups."""

from dataclasses import dataclass

from app.models import (
    Permission,
    Service,
    ServicePermission,
    ServiceUser,
    Template,
    TemplateRedacted,
    User, Organisation,
)


@dataclass(frozen=True)
class CacheInvalidationRule:
    """Describe how an ORM model change maps to a cache group."""

    namespace: str
    entity_id_attribute: str


CACHE_INVALIDATION_REGISTRY = {
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