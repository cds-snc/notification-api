from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import call

from app.cache.cache_dml import cache_invalidating_dml
from app.cache.cache_events import register_cache_orm_events
from app.cache.cache_invalidation_registry import CACHE_INVALIDATION_REGISTRY
from app.dao.permissions_dao import permission_dao
from app.dao.service_permissions_dao import dao_add_service_permission, dao_remove_service_permission
from app.dao.templates_dao import dao_update_template_process_type
from app.dao.users_dao import save_model_user
from app.models import (
    LETTER_TYPE,
    Permission,
    Service,
    ServicePermission,
    ServiceUser,
    Template,
    TemplateRedacted,
    User,
)
from sqlalchemy import delete
from tests.app.db import create_service, create_template, create_user

from app import db
from app.cache import cache_events


def test_register_cache_orm_events_is_thread_safe(mocker):
    registered_listeners = set()

    def contains(_target, event_name, listener):
        return (event_name, listener) in registered_listeners

    def listen(_target, event_name, listener):
        registered_listeners.add((event_name, listener))

    mocked_contains = mocker.patch("app.cache.cache_events.event.contains", side_effect=contains)
    mocked_listen = mocker.patch("app.cache.cache_events.event.listen", side_effect=listen)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: register_cache_orm_events(), range(20)))

    expected_listeners = {
        ("after_flush", cache_events._collect_cache_invalidations),
        ("after_commit", cache_events._invalidate_cache_after_commit),
        ("after_rollback", cache_events._clear_cache_invalidations_after_rollback),
        ("do_orm_execute", cache_events._intercept_bulk_operations),
    }
    assert registered_listeners == expected_listeners
    assert mocked_contains.call_count == 80
    assert mocked_listen.call_count == 4


def test_intercept_bulk_operations_uses_cache_invalidating_dml_metadata(mocker):
    session = mocker.Mock(info={})
    mocked_queue = mocker.patch("app.cache.cache_events._queue_entity_invalidations")
    statement = cache_invalidating_dml(delete(ServicePermission), service_id="service-id")
    orm_context = SimpleNamespace(
        is_delete=True,
        is_update=False,
        bind_mapper=SimpleNamespace(class_=ServicePermission),
        execution_options=statement.get_execution_options(),
        session=session,
    )

    cache_events._intercept_bulk_operations(orm_context)

    mocked_queue.assert_called_once_with(session, ServicePermission, {"service_id": "service-id"})


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


def test_user_and_template_cache_invalidation_registry():
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[User]] == [
        ("user", "id")
    ]
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[Permission]] == [
        ("user", "user_id")
    ]
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[Template]] == [
        ("template", "id")
    ]
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[TemplateRedacted]] == [
        ("template", "template_id")
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
        [
            call("service", str(service.id)),
            call("user", str(user.id)),
        ],
        any_order=True,
    )


def test_user_update_invalidates_user_cache(notify_db_session, mocker):
    register_cache_orm_events()
    user = create_user()
    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    save_model_user(user, update_dict={"name": "Updated name"})

    mocked_invalidate.assert_called_once_with("user", str(user.id))


def test_permission_removal_invalidates_user_cache(notify_db_session, sample_service, mocker):
    register_cache_orm_events()
    user = sample_service.users[0]
    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    permission_dao.remove_user_service_permissions(user=user, service=sample_service)
    db.session.commit()

    mocked_invalidate.assert_called_once_with("user", str(user.id))


def test_permission_removal_rollback_discards_user_cache_invalidation(notify_db_session, sample_service, mocker):
    register_cache_orm_events()
    user = sample_service.users[0]
    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    permission_dao.remove_user_service_permissions(user=user, service=sample_service)
    db.session.rollback()
    db.session.commit()

    mocked_invalidate.assert_not_called()


def test_template_update_invalidates_template_cache(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="template-cache-service", email_from="template-cache-service")
    template = create_template(service=service)
    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    template.name = "Updated template name"
    db.session.commit()

    mocked_invalidate.assert_called_once_with("template", str(template.id))


def test_template_bulk_update_invalidates_template_cache(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="template-bulk-cache-service", email_from="template-bulk-cache-service")
    template = create_template(service=service)
    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    dao_update_template_process_type(template.id, "priority")

    mocked_invalidate.assert_called_once_with("template", str(template.id))
