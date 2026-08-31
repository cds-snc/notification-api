from unittest.mock import call

from app import db
from app.cache.cache_events import register_cache_orm_events
from app.cache.cache_invalidation_registry import CACHE_INVALIDATION_REGISTRY
from app.dao.service_permissions_dao import dao_add_service_permission, dao_remove_service_permission
from app.models import LETTER_TYPE, Service, ServicePermission, ServiceUser
from tests.app.db import create_service, create_user


def test_service_cache_invalidation_registry():
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[Service]] == [
        ("service", "id")
    ]
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[ServicePermission]] == [
        ("service", "service_id")
    ]
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[ServiceUser]] == [
        ("service", "service_id"),
        ("user", "user_id"),
    ]


def test_service_update_invalidates_service_cache(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="service-cache-update", email_from="service-cache-update")

    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    service.name = "service-cache-update-2"
    db.session.add(service)
    db.session.commit()

    mocked_invalidate.assert_called_once_with("service", str(service.id))


def test_service_permission_changes_invalidate_service_cache(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="service-cache-perms", email_from="service-cache-perms")

    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    dao_add_service_permission(service.id, LETTER_TYPE)
    dao_remove_service_permission(service.id, LETTER_TYPE)

    mocked_invalidate.assert_has_calls([call("service", str(service.id)), call("service", str(service.id))])


def test_service_user_change_invalidates_service_and_user_caches(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="service-cache-user", email_from="service-cache-user")
    user = create_user()

    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    db.session.add(ServiceUser(service_id=service.id, user_id=user.id))
    db.session.commit()

    mocked_invalidate.assert_has_calls(
        [call("service", str(service.id)), call("user", str(user.id))],
        any_order=True,
    )