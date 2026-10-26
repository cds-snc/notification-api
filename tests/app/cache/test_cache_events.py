import json
import logging
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from types import SimpleNamespace
from unittest.mock import call

import pytest
from flask import Flask
from notifications_utils import logging as notify_logging
from sqlalchemy import delete
from tests.app.db import create_service, create_template, create_user

from app import db
from app.cache import cache_events
from app.cache.cache_dml import cache_invalidating_dml
from app.cache.cache_events import register_cache_orm_events
from app.cache.cache_invalidation_registry import CACHE_INVALIDATION_REGISTRY, CacheInvalidationRule
from app.caching import dogpile_region, init_dogpile_cache, _unlink_exact_keys, invalidate_group_keys
from app.dao.permissions_dao import permission_dao
from app.dao.service_permissions_dao import dao_add_service_permission, dao_remove_service_permission
from app.dao.templates_dao import dao_update_template_process_type
from app.dao.users_dao import save_model_user
from app.models import (
    LETTER_TYPE,
    Notification,
    Permission,
    Service,
    ServicePermission,
    ServiceUser,
    Template,
    TemplateRedacted,
    User,
)


@pytest.mark.parametrize("app_name", ["api", "celery"])
@pytest.mark.parametrize("log_level", ["INFO", "WARNING"])
def test_cache_logs_use_application_stdout_handlers_without_app_context(mocker, monkeypatch, app_name, log_level):
    app = Flask(app_name)
    app.config.update(DEBUG=False, NOTIFY_APP_NAME=app_name, NOTIFY_LOG_LEVEL=log_level, NOTIFY_LOG_PATH="")
    output = StringIO()
    monkeypatch.setattr("sys.stdout", output)
    for name in (app_name, "utils", "app.caching", "app.cache.cache_events"):
        module_logger = logging.getLogger(name)
        # Alembic's fileConfig disables existing loggers during database setup.
        monkeypatch.setattr(module_logger, "disabled", False)
        monkeypatch.setattr(module_logger, "handlers", [])
        monkeypatch.setattr(module_logger, "level", logging.NOTSET)
        monkeypatch.setattr(module_logger, "propagate", True)
    monkeypatch.setattr(logging.getLogger(), "handlers", [])
    monkeypatch.setattr(logging.getLogger(), "level", logging.WARNING)
    notify_logging.init_app(app)
    mocker.patch.object(dogpile_region, "configure")
    init_dogpile_cache(app)
    init_dogpile_cache(app)
    output.seek(0)
    output.truncate()

    redis_client = mocker.Mock()
    redis_client.scan.return_value = (0, [b"template:entity-id:cached"])
    redis_client.delete.return_value = 1
    mocker.patch("app.caching._get_redis_client_from_region", return_value=redis_client)
    instance = Template(id="entity-id")
    session = SimpleNamespace(new={instance}, dirty=set(), deleted=set(), info={})

    cache_events._collect_cache_invalidations(session, mocker.Mock())
    assert invalidate_group_keys("template", "entity-id") == 1

    records = [json.loads(line) for line in output.getvalue().splitlines()]
    if log_level == "WARNING":
        assert records == []
    else:
        assert len(records) == 2
        assert [record["name"] for record in records] == [
            "app.cache.cache_events", "app.caching"
        ]
        assert all(record["application"] == app_name for record in records)
        assert all(record["levelname"] == "INFO" for record in records)
        assert all(record["requestId"] == "no-request-id" for record in records)
        assert "cache.collect_invalidations instances=1 invalidations=1" in records[0]["message"]
        assert "cache.invalidate_group_keys namespace=template" in records[1]["message"]
        assert "matched=1 deleted=1" in records[1]["message"]


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


def test_collect_cache_invalidations_logs_performance(mocker):
    class CachedModel:
        pass

    instance = CachedModel()
    instance.id = "entity-id"
    session = SimpleNamespace(new={instance}, dirty=set(), deleted=set(), info={})
    rule = CacheInvalidationRule(namespace="service", entity_id_attribute="id")
    mocker.patch.object(
        cache_events, "CACHE_INVALIDATION_REGISTRY", {CachedModel: (rule,)}
    )
    mocker.patch("app.cache.cache_events.perf_counter", side_effect=[10, 10.125])
    mocked_logger = mocker.patch("app.cache.cache_events.logger")

    cache_events._collect_cache_invalidations(session, mocker.Mock())

    mocked_logger.info.assert_called_once_with(
        "cache.collect_invalidations instances=1 invalidations=1 elapsed_ms=125.00"
    )


def test_collect_cache_invalidations_skips_inserts_when_rule_opts_out(mocker):
    class CachedModel:
        pass

    inserted, updated, deleted = CachedModel(), CachedModel(), CachedModel()
    inserted.id, updated.id, deleted.id = "inserted", "updated", "deleted"
    session = SimpleNamespace(new={inserted}, dirty={updated}, deleted={deleted}, info={})
    rule = CacheInvalidationRule(namespace="notification", entity_id_attribute="id", invalidate_on_insert=False)
    mocker.patch.object(cache_events, "CACHE_INVALIDATION_REGISTRY", {CachedModel: (rule,)})

    cache_events._collect_cache_invalidations(session, mocker.Mock())

    assert session.info[cache_events._CACHE_INVALIDATIONS_KEY] == {
        ("notification", "updated"),
        ("notification", "deleted"),
    }


def test_notification_rule_skips_inserts():
    assert [
        (rule.namespace, rule.entity_id_attribute, rule.invalidate_on_insert)
        for rule in CACHE_INVALIDATION_REGISTRY[Notification]
    ] == [("notification", "id", False)]


def test_invalidate_group_keys_logs_performance(mocker):
    redis_client = mocker.Mock()
    redis_client.scan.side_effect = [
        (1, [b"service:entity-id:first", b"service:entity-id:second"]),
        (0, [b"service:entity-id:third"]),
    ]
    redis_client.delete.side_effect = [2, 1]
    mocker.patch(
        "app.caching._get_redis_client_from_region", return_value=redis_client
    )
    mocker.patch("app.caching.perf_counter", side_effect=[20, 20.125])
    mocked_logger = mocker.patch("app.caching.logger")

    deleted = invalidate_group_keys("service", "entity-id")

    assert deleted == 3
    mocked_logger.info.assert_called_once_with(
        "cache.invalidate_group_keys namespace=service batch_size=500 scans=2 matched=3 deleted=3 elapsed_ms=125.00"
    )


def test_exact_key_invalidation_deletes_deduplicated_keys_in_batches(mocker):
    redis_client = mocker.Mock()
    redis_client.unlink.side_effect = [2, 1]
    mocker.patch("app.caching._get_redis_client_from_region", return_value=redis_client)

    deleted = _unlink_exact_keys("notification", ["first", "second", "first", "third"], region=None, batch_size=2)

    assert deleted == 3
    assert redis_client.unlink.call_args_list == [
        call("notification:first", "notification:second"),
        call("notification:third"),
    ]
    redis_client.scan.assert_not_called()


def test_after_commit_invalidates_each_namespace_in_one_batch(mocker):
    session = SimpleNamespace(info={cache_events._CACHE_INVALIDATIONS_KEY: {
        ("notification", "first"), ("notification", "second"), ("service", "service-id")
    }})
    invalidate = mocker.patch("app.cache.cache_events.invalidate_cache_entities")

    cache_events._invalidate_cache_after_commit(session)

    calls = {c.args[0]: set(c.args[1]) for c in invalidate.call_args_list}
    assert calls == {"notification": {"first", "second"}, "service": {"service-id"}}
    assert session.info == {}


def test_after_commit_failure_in_one_namespace_does_not_block_others(mocker):
    session = SimpleNamespace(info={cache_events._CACHE_INVALIDATIONS_KEY: {
        ("notification", "first"), ("service", "service-id")
    }})
    invalidate = mocker.patch(
        "app.cache.cache_events.invalidate_cache_entities",
        side_effect=lambda namespace, _ids: (_ for _ in ()).throw(RuntimeError()) if namespace == "notification" else 1,
    )
    mocked_logger = mocker.patch("app.cache.cache_events.logger")

    cache_events._invalidate_cache_after_commit(session)

    assert invalidate.call_count == 2
    mocked_logger.exception.assert_called_once()


def test_queue_cache_invalidations_resolves_model_rules_and_accepts_iterables(mocker):
    mocker.patch("app.cache.cache_events.event.contains", return_value=True)
    session = SimpleNamespace(info={})

    cache_events.queue_cache_invalidations(session, Notification, id=(i for i in ["a", "b"]))
    cache_events.queue_cache_invalidations(session, Notification, id="c")

    assert session.info[cache_events._CACHE_INVALIDATIONS_KEY] == {
        ("notification", "a"),
        ("notification", "b"),
        ("notification", "c"),
    }


def test_queue_cache_invalidations_is_noop_when_listeners_not_registered(mocker):
    mocker.patch("app.cache.cache_events.event.contains", return_value=False)
    session = SimpleNamespace(info={})

    cache_events.queue_cache_invalidations(session, Notification, id=["a"])

    assert session.info == {}


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

    mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

    service.name = "service-cache-update-2"
    db.session.add(service)
    db.session.commit()

    mocked_invalidate.assert_called_once_with("service", str(service.id))


def test_service_permission_changes_invalidate_service_cache(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="service-cache-perms", email_from="service-cache-perms")

    mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

    dao_add_service_permission(service.id, LETTER_TYPE)
    dao_remove_service_permission(service.id, LETTER_TYPE)

    mocked_invalidate.assert_has_calls([call("service", str(service.id)), call("service", str(service.id))])


def test_service_user_change_invalidates_service_and_user_caches(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="service-cache-user", email_from="service-cache-user")
    user = create_user()

    mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

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
    mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

    save_model_user(user, update_dict={"name": "Updated name"})

    mocked_invalidate.assert_called_once_with("user", str(user.id))


def test_permission_removal_invalidates_user_cache(notify_db_session, sample_service, mocker):
    register_cache_orm_events()
    user = sample_service.users[0]
    mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

    permission_dao.remove_user_service_permissions(user=user, service=sample_service)
    db.session.commit()

    mocked_invalidate.assert_called_once_with("user", str(user.id))


def test_permission_removal_rollback_discards_user_cache_invalidation(notify_db_session, sample_service, mocker):
    register_cache_orm_events()
    user = sample_service.users[0]
    mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

    permission_dao.remove_user_service_permissions(user=user, service=sample_service)
    db.session.rollback()
    db.session.commit()

    mocked_invalidate.assert_not_called()


def test_template_update_invalidates_template_cache(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="template-cache-service", email_from="template-cache-service")
    template = create_template(service=service)
    mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

    template.name = "Updated template name"
    db.session.commit()

    mocked_invalidate.assert_called_once_with("template", str(template.id))


def test_template_bulk_update_invalidates_template_cache(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="template-bulk-cache-service", email_from="template-bulk-cache-service")
    template = create_template(service=service)
    mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

    dao_update_template_process_type(template.id, "priority")

    mocked_invalidate.assert_called_once_with("template", str(template.id))
