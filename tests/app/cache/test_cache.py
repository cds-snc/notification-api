import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import call
from uuid import UUID

import pytest
from dogpile.cache import make_region
from dogpile.cache.api import NO_VALUE
from fakeredis import FakeRedis
from flask import Flask, jsonify
from freezegun import freeze_time
from tests import create_authorization_header
from tests.app.db import create_notification, create_service, create_template, create_user
from tests.conftest import set_config
from app import db
from app.cache import cache_events
from app.cache.cache_events import register_cache_orm_events
from app.cache.cache_invalidation_registry import CACHE_INVALIDATION_REGISTRY
from app.caching import (
    _json_cache_deserializer,
    _json_cache_serializer,
    cache_key_generator,
    cache_on_arguments,
    exact_cache_key,
    init_dogpile_cache,
    invalidate_cache_entities,
    short_lived_region,
)
from app.dao import notifications_dao
from app.dao.permissions_dao import permission_dao
from app.dao.service_permissions_dao import (
    dao_add_service_permission,
    dao_remove_service_permission,
)
from app.dao.users_dao import save_model_user
from app.models import (
    LETTER_TYPE,
    NOTIFICATION_DELIVERED,
    Notification,
    Permission,
    Service,
    ServicePermission,
    ServiceUser,
    Template,
    TemplateRedacted,
    User,
)


def _make_memory_region(expiration_time=600):
    return make_region(
        function_key_generator=cache_key_generator,
        serializer=_json_cache_serializer,
        deserializer=_json_cache_deserializer,
    ).configure(
        "dogpile.cache.memory",
        expiration_time=expiration_time,
    )


class TestCacheAccessLogging:
    def test_logs_regeneration_and_cache_reuse(self, mocker):
        mocker.patch("app.caching.dogpile_region", _make_memory_region())
        mocker.patch("app.caching.perf_counter", side_effect=[10, 10.01234, 20, 20.001])
        logger = mocker.patch("app.caching.logger")
        creator_calls = []

        @cache_on_arguments(namespace="service", group_by="service_id")
        def fetch(service_id):
            creator_calls.append(service_id)
            return {"id": service_id}

        assert fetch("abc-123") == {"id": "abc-123"}
        assert fetch(service_id="abc-123") == {"id": "abc-123"}
        assert creator_calls == ["abc-123"]
        assert fetch.__name__ == "fetch"
        function = f"{fetch.__module__}.{fetch.__qualname__}"
        assert logger.info.call_args_list == [
            call(
                f"dao.execution_time function={function} elapsed_ms=12.34 "
                "cache_namespace=service cache_outcome=regenerated"
            ),
            call(
                f"dao.execution_time function={function} elapsed_ms=1.00 "
                "cache_namespace=service cache_outcome=reused"
            ),
        ]
        fetch.invalidate("abc-123")
        assert fetch.get("abc-123") is NO_VALUE

    def test_logs_error_and_recovers_on_next_call(self, mocker):
        mocker.patch("app.caching.dogpile_region", _make_memory_region())
        mocker.patch("app.caching.perf_counter", side_effect=[10, 10.002, 20, 20.003])
        logger = mocker.patch("app.caching.logger")

        @cache_on_arguments(namespace="service", group_by="service_id")
        def fetch(service_id):
            if service_id == "failed":
                raise ValueError("failed")
            return {"id": service_id}

        with pytest.raises(ValueError, match="failed"):
            fetch("failed")
        assert fetch("abc-123") == {"id": "abc-123"}
        function = f"{fetch.__module__}.{fetch.__qualname__}"
        assert logger.info.call_args_list == [
            call(
                f"dao.execution_time function={function} elapsed_ms=2.00 "
                "cache_namespace=service cache_outcome=error"
            ),
            call(
                f"dao.execution_time function={function} elapsed_ms=3.00 "
                "cache_namespace=service cache_outcome=regenerated"
            ),
        ]


@pytest.fixture
def notification_cache(client, notify_api, mocker):
    register_cache_orm_events()
    redis_client = FakeRedis()
    region = make_region(
        serializer=_json_cache_serializer,
        deserializer=_json_cache_deserializer,
    ).configure("dogpile.cache.redis", expiration_time=60, arguments={"redis_expiration_time": 120})
    region.backend.writer_client = redis_client
    region.backend.reader_client = redis_client
    mocker.patch.object(short_lived_region, "backend", region.backend)
    with set_config(notify_api, "FF_USE_DOGPILE_CACHING", True):
        yield redis_client


def _snapshot(notification):
    return notifications_dao.get_cached_notification_snapshot(notification.service_id, notification.id)


@pytest.mark.parametrize("route", ["v1", "v2", "admin"])
@pytest.mark.parametrize("notification_fixture", ["sample_notification", "sample_email_notification", "sample_letter_notification"])
def test_notification_cache_preserves_response_and_reuses_snapshot(
    client, notification_cache, request, mocker, route, notification_fixture
):
    notification = request.getfixturevalue(notification_fixture)
    if route == "admin":
        path = f"/service/{notification.service_id}/notifications/{notification.id}"
        headers = [create_authorization_header()]
    else:
        path = f"{'/v2' if route == 'v2' else ''}/notifications/{notification.id}"
        headers = [create_authorization_header(service_id=notification.service_id)]
    with set_config(client.application, "FF_USE_DOGPILE_CACHING", False):
        expected = client.get(path, headers=headers)
    assert expected.status_code == 200
    first = client.get(path, headers=headers)
    assert first.status_code == 200
    # Compare raw bytes so key order (not just content) matches the uncached response
    assert first.data == expected.data
    assert notification_cache.exists(exact_cache_key("notification", notification.id))
    mocker.patch.object(notifications_dao, "Notification", side_effect=AssertionError("Cache hit queried database"))
    second = client.get(path, headers=headers)
    assert second.status_code == 200
    assert second.data == expected.data


def test_notification_snapshot_is_shared_by_all_routes(notification_cache, sample_notification):
    _snapshot(sample_notification)
    assert notification_cache.keys("notification:*") == [exact_cache_key("notification", sample_notification.id).encode()]


@pytest.mark.parametrize("prefix", ["", "/v2"])
def test_notification_cache_checks_service_ownership_on_hits(client, notification_cache, sample_notification, prefix):
    notification = sample_notification
    assert _snapshot(notification) is not None
    other_service = create_service(service_name="other-cache-service", email_from="other-cache-service")
    assert notifications_dao.get_cached_notification_snapshot(other_service.id, notification.id) is None
    response = client.get(
        f"{prefix}/notifications/{notification.id}",
        headers=[create_authorization_header(service_id=other_service.id)],
    )
    assert response.status_code == 404


def test_notification_cache_normalizes_ids_and_does_not_cache_missing(notification_cache, sample_notification):
    service_id = sample_notification.service_id
    first = notifications_dao.get_cached_notification_snapshot(service_id, sample_notification.id)
    second = notifications_dao.get_cached_notification_snapshot(str(service_id), str(sample_notification.id))
    assert jsonify(first).get_json() == jsonify(second).get_json()
    missing_id = UUID("aaaaaaaa-1111-2222-3333-444444444444")
    assert notifications_dao.get_cached_notification_snapshot(service_id, missing_id) is None
    assert not notification_cache.exists(exact_cache_key("notification", missing_id))


def test_notification_insert_does_not_queue_invalidation(notification_cache, sample_template, mocker):
    unlink = mocker.spy(notification_cache, "unlink")
    create_notification(template=sample_template)
    unlink.assert_not_called()
    assert db.session.info.get(cache_events._CACHE_INVALIDATIONS_KEY) is None


def test_orm_notification_update_invalidates_after_commit(notification_cache, sample_notification):
    _snapshot(sample_notification)
    sample_notification.status = NOTIFICATION_DELIVERED
    notifications_dao.dao_update_notification(sample_notification)
    assert not notification_cache.exists(exact_cache_key("notification", sample_notification.id))
    assert _snapshot(sample_notification)["v2"]["status"] == NOTIFICATION_DELIVERED


def test_bulk_notification_update_invalidates_once_after_commit(notification_cache, sample_notification, mocker):
    notification = sample_notification
    _snapshot(notification)
    unlink = mocker.spy(notification_cache, "unlink")
    scan = mocker.spy(notification_cache, "scan")
    notification.status = NOTIFICATION_DELIVERED
    notifications_dao.update_notification_statuses([notification])
    unlink.assert_called_once_with(exact_cache_key("notification", notification.id))
    scan.assert_not_called()
    refreshed = _snapshot(notification)
    assert refreshed["v1"]["status"] == NOTIFICATION_DELIVERED
    assert refreshed["v2"]["status"] == NOTIFICATION_DELIVERED
    assert refreshed["admin"]["status"] == NOTIFICATION_DELIVERED


def test_notification_cache_rollback_discards_invalidation(notification_cache, sample_notification, mocker):
    notification = sample_notification
    _snapshot(notification)
    unlink = mocker.spy(notification_cache, "unlink")
    notification.status = NOTIFICATION_DELIVERED
    db.session.flush()
    db.session.rollback()
    unlink.assert_not_called()
    assert notification_cache.exists(exact_cache_key("notification", notification.id))
    db.session.commit()
    unlink.assert_not_called()


def test_notification_delete_evicts_cached_snapshot(notification_cache, sample_notification):
    notification_id = sample_notification.id
    service_id = sample_notification.service_id
    _snapshot(sample_notification)
    notifications_dao.dao_delete_notifications_by_id(notification_id)
    assert not notification_cache.exists(exact_cache_key("notification", notification_id))
    assert notifications_dao.get_cached_notification_snapshot(service_id, notification_id) is None


@pytest.mark.parametrize("operation", ["reference", "timeout"])
def test_notification_bulk_dml_evicts_cached_snapshot(notification_cache, sample_notification, operation):
    notification = sample_notification
    notification_id = notification.id
    notification.reference = str(notification.id)
    db.session.commit()
    _snapshot(notification)
    if operation == "reference":
        assert notifications_dao.dao_update_notifications_by_reference(
            [notification.reference], {"status": NOTIFICATION_DELIVERED}
        ) == (1, 0)
    else:
        notifications_dao.dao_timeout_notifications(0)
    assert not notification_cache.exists(exact_cache_key("notification", notification_id))


def test_notification_cache_uses_short_lived_region_expiry(notification_cache, sample_notification, mocker):
    notification_id = sample_notification.id
    mocker.patch.object(short_lived_region, "expiration_time", 5)
    with freeze_time() as frozen:
        snapshot = _snapshot(sample_notification)
        db.session.connection().execute(
            Notification.__table__.update().where(Notification.id == notification_id).values(status=NOTIFICATION_DELIVERED)
        )
        db.session.commit()
        assert _snapshot(sample_notification)["v1"]["status"] == snapshot["v1"]["status"]
        frozen.tick(6)
        assert _snapshot(sample_notification)["v1"]["status"] == NOTIFICATION_DELIVERED


def test_notification_snapshot_supports_dogpile_helpers(notification_cache, sample_notification):
    cached_fn = notifications_dao.dao_get_notification_snapshot_cached
    cached_fn(sample_notification.id)
    assert notification_cache.exists(exact_cache_key("notification", sample_notification.id))
    cached_fn.invalidate(sample_notification.id)
    assert not notification_cache.exists(exact_cache_key("notification", sample_notification.id))


def test_notification_snapshot_logs_cache_outcome(notification_cache, sample_notification, mocker):
    logger = mocker.patch("app.caching.logger")
    notifications_dao.dao_get_notification_snapshot_cached(sample_notification.id)
    notifications_dao.dao_get_notification_snapshot_cached(sample_notification.id)
    messages = [c.args[0] for c in logger.info.call_args_list if c.args[0].startswith("dao.execution_time")]
    assert [m.split("cache_outcome=")[1] for m in messages] == ["regenerated", "reused"]
    assert all("function=app.dao.notifications_dao.dao_get_notification_snapshot_cached" in m for m in messages)


class TestCacheNamespaces:
    def test_exact_namespace_rejects_functions_with_extra_arguments(self):
        with pytest.raises(TypeError, match="must take only 'notification_id'"):

            @cache_on_arguments(namespace="notification", group_by="notification_id")
            def fetch(notification_id, service_id):
                pass

    def test_decorator_rejects_missing_group_by_argument(self):
        with pytest.raises(TypeError, match="must accept the group_by argument 'service_id'"):

            @cache_on_arguments(namespace="service", group_by="service_id")
            def fetch(user_id):
                pass

    def test_exact_namespace_uses_short_lived_region_and_exact_key(self, mocker):
        default_region = mocker.patch("app.caching.dogpile_region")
        short_region = mocker.patch("app.caching.short_lived_region")
        captured = {}
        short_region.cache_on_arguments.return_value = lambda creator: captured.setdefault("creator", creator)

        @cache_on_arguments(namespace="notification", group_by="notification_id")
        def fetch(notification_id):
            pass

        short_region.cache_on_arguments.assert_called_once_with(namespace="notification")
        default_region.cache_on_arguments.assert_not_called()
        notification_id = UUID("d4e5f6a7-1234-5678-9abc-def012345678")
        generate_key = cache_key_generator("notification", captured["creator"])
        assert generate_key(notification_id) == generate_key(str(notification_id)) == f"notification:{notification_id}"

    def test_invalidate_cache_entities_dispatches_on_namespace_strategy(self, mocker):
        unlink = mocker.patch("app.caching._unlink_exact_keys")
        scan = mocker.patch("app.caching.invalidate_group_keys")

        invalidate_cache_entities("notification", ["a", "b"])
        invalidate_cache_entities("service", ["s1", "s2", "s1"])

        unlink.assert_called_once_with("notification", ["a", "b"], short_lived_region)
        assert [c.args[:2] for c in scan.call_args_list] == [("service", "s1"), ("service", "s2")]

    def test_serializer_preserves_key_order(self):
        assert _json_cache_serializer({"b": 1, "a": 2}) == b'{"b":1,"a":2}'


class TestCacheEvents:
    def test_register_cache_orm_events_is_thread_safe(self, mocker):
        registered_listeners = set()

        def contains(_target, event_name, listener):
            return (event_name, listener) in registered_listeners

        def listen(_target, event_name, listener):
            registered_listeners.add((event_name, listener))

        mocked_contains = mocker.patch(
            "app.cache.cache_events.event.contains", side_effect=contains
        )
        mocked_listen = mocker.patch(
            "app.cache.cache_events.event.listen", side_effect=listen
        )

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

    def test_service_update_invalidates_service_cache(self, notify_db_session, mocker):
        register_cache_orm_events()
        service = create_service(
            service_name="service-cache-update", email_from="service-cache-update"
        )

        mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

        service.name = "service-cache-update-2"
        db.session.add(service)
        db.session.commit()

        mocked_invalidate.assert_called_once_with("service", str(service.id))

    def test_service_permission_changes_invalidate_service_cache(
        self, notify_db_session, mocker
    ):
        register_cache_orm_events()
        service = create_service(
            service_name="service-cache-perms", email_from="service-cache-perms"
        )

        mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

        dao_add_service_permission(service.id, LETTER_TYPE)
        dao_remove_service_permission(service.id, LETTER_TYPE)

        mocked_invalidate.assert_has_calls(
            [call("service", str(service.id)), call("service", str(service.id))]
        )

    def test_service_user_change_invalidates_service_and_user_caches(
        self, notify_db_session, mocker
    ):
        register_cache_orm_events()
        service = create_service(
            service_name="service-cache-user", email_from="service-cache-user"
        )
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

    def test_user_update_invalidates_user_cache(self, notify_db_session, mocker):
        register_cache_orm_events()
        user = create_user()
        mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

        save_model_user(user, update_dict={"name": "Updated name"})

        mocked_invalidate.assert_called_once_with("user", str(user.id))

    def test_permission_removal_rollback_discards_user_cache_invalidation(
        self, notify_db_session, sample_service, mocker
    ):
        register_cache_orm_events()
        user = sample_service.users[0]
        mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

        permission_dao.remove_user_service_permissions(
            user=user, service=sample_service
        )
        db.session.rollback()
        db.session.commit()

        mocked_invalidate.assert_not_called()

    def test_template_update_invalidates_template_cache(
        self, notify_db_session, mocker
    ):
        register_cache_orm_events()
        service = create_service(
            service_name="template-cache-service", email_from="template-cache-service"
        )
        template = create_template(service=service)
        mocked_invalidate = mocker.patch("app.caching.invalidate_group_keys")

        template.name = "Updated template name"
        db.session.commit()

        mocked_invalidate.assert_called_once_with("template", str(template.id))


class TestCacheInvalidationRegistry:
    def test_service_cache_invalidation_registry(self):
        assert [
            (rule.namespace, rule.entity_id_attribute)
            for rule in CACHE_INVALIDATION_REGISTRY[Service]
        ] == [("service", "id")]
        assert [
            (rule.namespace, rule.entity_id_attribute)
            for rule in CACHE_INVALIDATION_REGISTRY[ServicePermission]
        ] == [("service", "service_id")]
        assert [
            (rule.namespace, rule.entity_id_attribute)
            for rule in CACHE_INVALIDATION_REGISTRY[ServiceUser]
        ] == [
            ("service", "service_id"),
            ("user", "user_id"),
        ]

    def test_user_and_template_cache_invalidation_registry(self):
        assert [
            (rule.namespace, rule.entity_id_attribute)
            for rule in CACHE_INVALIDATION_REGISTRY[User]
        ] == [("user", "id")]
        assert [
            (rule.namespace, rule.entity_id_attribute)
            for rule in CACHE_INVALIDATION_REGISTRY[Permission]
        ] == [("user", "user_id")]
        assert [
            (rule.namespace, rule.entity_id_attribute)
            for rule in CACHE_INVALIDATION_REGISTRY[Template]
        ] == [("template", "id")]
        assert [
            (rule.namespace, rule.entity_id_attribute)
            for rule in CACHE_INVALIDATION_REGISTRY[TemplateRedacted]
        ] == [("template", "template_id")]


class TestExpirationEviction:
    def test_value_is_served_from_cache_before_expiry(self):
        region = _make_memory_region(expiration_time=10)
        call_count = 0

        @region.cache_on_arguments(namespace="svc")
        def fetch(service_id):
            nonlocal call_count
            call_count += 1
            return {"id": service_id, "name": "My Service"}

        result_a = fetch("abc-123")
        result_b = fetch("abc-123")

        assert result_a == result_b
        assert call_count == 1, "Creator should only be called once while cache is warm"

    def test_value_is_regenerated_after_expiry(self):
        region = _make_memory_region(expiration_time=1)
        call_count = 0

        @region.cache_on_arguments(namespace="svc")
        def fetch(service_id):
            nonlocal call_count
            call_count += 1
            return {"id": service_id, "count": call_count}

        first = fetch("abc-123")
        assert first["count"] == 1

        time.sleep(1.1)

        second = fetch("abc-123")
        assert second["count"] == 2, "Creator should be re-invoked after expiration"
        assert call_count == 2

    def test_different_keys_are_cached_independently(self):
        region = _make_memory_region(expiration_time=10)
        call_count = 0

        @region.cache_on_arguments(namespace="svc")
        def fetch(service_id):
            nonlocal call_count
            call_count += 1
            return {"id": service_id}

        fetch("aaaaaaaa-1111-2222-3333-444444444444")
        fetch("bbbbbbbb-1111-2222-3333-444444444444")
        fetch("aaaaaaaa-1111-2222-3333-444444444444")
        fetch("bbbbbbbb-1111-2222-3333-444444444444")

        assert (
            call_count == 2
        ), "Each unique key should trigger exactly one creator call"


class TestExplicitInvalidation:
    def test_invalidate_forces_regeneration(self):
        region = _make_memory_region(expiration_time=600)
        call_count = 0

        @region.cache_on_arguments(namespace="svc")
        def fetch(service_id):
            nonlocal call_count
            call_count += 1
            return {"id": service_id, "version": call_count}

        first = fetch("abc-123")
        assert first["version"] == 1

        fetch.invalidate("abc-123")  # type: ignore[attr-defined]

        second = fetch("abc-123")
        assert second["version"] == 2, "Creator must be re-invoked after invalidation"

    def test_invalidate_only_affects_targeted_key(self):
        region = _make_memory_region(expiration_time=600)
        call_count = 0

        @region.cache_on_arguments(namespace="svc")
        def fetch(service_id):
            nonlocal call_count
            call_count += 1
            return {"id": service_id, "version": call_count}

        fetch("aaaaaaaa-1111-2222-3333-444444444444")
        fetch("bbbbbbbb-1111-2222-3333-444444444444")
        assert call_count == 2

        fetch.invalidate("aaaaaaaa-1111-2222-3333-444444444444")  # type: ignore[attr-defined]

        fetch("aaaaaaaa-1111-2222-3333-444444444444")
        fetch("bbbbbbbb-1111-2222-3333-444444444444")

        assert call_count == 3, "Only the invalidated key should regenerate"


class TestRegionInvalidation:
    def test_hard_invalidation_forces_all_keys_to_regenerate(self):
        region = _make_memory_region(expiration_time=600)
        call_count = 0

        @region.cache_on_arguments(namespace="svc")
        def fetch(service_id):
            nonlocal call_count
            call_count += 1
            return {"id": service_id, "version": call_count}

        fetch("aaaaaaaa-1111-2222-3333-444444444444")
        fetch("bbbbbbbb-1111-2222-3333-444444444444")
        assert call_count == 2

        region.invalidate(hard=True)

        fetch("aaaaaaaa-1111-2222-3333-444444444444")
        fetch("bbbbbbbb-1111-2222-3333-444444444444")
        assert call_count == 4, "Hard invalidation should force all keys to regenerate"

    def test_soft_invalidation_returns_stale_then_regenerates(self):
        region = _make_memory_region(expiration_time=600)
        call_count = 0

        @region.cache_on_arguments(namespace="svc")
        def fetch(service_id):
            nonlocal call_count
            call_count += 1
            return {"id": service_id, "version": call_count}

        first = fetch("abc-123")
        assert first["version"] == 1

        region.invalidate(hard=False)
        fetch("abc-123")

        assert call_count == 2


class TestDecoratorHelpers:
    def test_set_injects_value_without_calling_creator(self):
        region = _make_memory_region(expiration_time=600)
        call_count = 0

        @region.cache_on_arguments(namespace="svc")
        def fetch(service_id):
            nonlocal call_count
            call_count += 1
            return {"id": service_id}

        fetch.set({"id": "abc-123", "injected": True}, "abc-123")  # type: ignore[attr-defined]

        result = fetch("abc-123")
        assert result["injected"] is True
        assert call_count == 0, "Creator should not be called when value is pre-seeded"

    def test_get_returns_no_value_for_missing_key(self):
        region = _make_memory_region(expiration_time=600)

        @region.cache_on_arguments(namespace="svc")
        def fetch(service_id):
            return {"id": service_id}

        result = fetch.get("never-cached")  # type: ignore[attr-defined]
        assert result is NO_VALUE

    def test_refresh_forces_regeneration_and_returns_new_value(self):
        region = _make_memory_region(expiration_time=600)
        call_count = 0

        @region.cache_on_arguments(namespace="svc")
        def fetch(service_id):
            nonlocal call_count
            call_count += 1
            return {"id": service_id, "version": call_count}

        fetch("abc-123")
        assert call_count == 1

        refreshed = fetch.refresh("abc-123")  # type: ignore[attr-defined]
        assert refreshed["version"] == 2
        assert call_count == 2


class TestRegionDelete:
    def test_delete_removes_cached_value(self):
        region = _make_memory_region(expiration_time=600)

        region.set("mykey", "hello")
        assert region.get("mykey") == "hello"

        region.delete("mykey")
        assert region.get("mykey") is NO_VALUE


class TestCacheKeys:
    def test_key_contains_namespace_and_function_name(self):
        def dao_fetch_service_by_id_cached(service_id):
            pass

        gen = cache_key_generator("service", dao_fetch_service_by_id_cached)
        key = gen("d4e5f6a7-1234-5678-9abc-def012345678")

        assert "service:" in key
        assert "dao_fetch_service_by_id_cached" in key
        assert "d4e5f6a7-1234-5678-9abc-def012345678" in key

    def test_grouped_key_uses_compact_prefix_and_excludes_primary_param_from_fingerprint(
        self,
    ):
        def dao_fetch_service_by_id_cached(service_id, only_active=False):
            pass

        dao_fetch_service_by_id_cached.__cache_group__ = ("service", "service_id")
        gen = cache_key_generator("service", dao_fetch_service_by_id_cached)
        key = gen("d4e5f6a7-1234-5678-9abc-def012345678", False)

        assert key.startswith(
            "service:d4e5f6a7-1234-5678-9abc-def012345678:dao_fetch_service_by_id_cached:"
        )
        assert "only_active=False" in key
        assert "service_id=" not in key

    def test_template_key_groups_by_template_id_and_fingerprints_service_id(self):
        def dao_get_template_by_id_cached(template_id, service_id):
            pass

        dao_get_template_by_id_cached.__cache_group__ = ("template", "template_id")
        gen = cache_key_generator("template", dao_get_template_by_id_cached)
        key = gen(
            UUID("d4e5f6a7-1234-5678-9abc-def012345678"),
            UUID("a1b2c3d4-1234-5678-9abc-def012345678"),
        )

        assert key.startswith(
            "template:d4e5f6a7-1234-5678-9abc-def012345678:dao_get_template_by_id_cached:"
        )
        assert "service_id=a1b2c3d4-1234-5678-9abc-def012345678" in key

    def test_same_args_produce_same_key(self):
        def my_func(service_id):
            pass

        gen = cache_key_generator("ns", my_func)
        assert gen("aaa-bbb-ccc-ddd-eee") == gen("aaa-bbb-ccc-ddd-eee")

    def test_different_args_produce_different_keys(self):
        def my_func(service_id):
            pass

        gen = cache_key_generator("ns", my_func)
        key_a = gen("aaaaaaaa-1111-2222-3333-444444444444")
        key_b = gen("bbbbbbbb-1111-2222-3333-444444444444")
        assert key_a != key_b

    def test_non_uuid_args_are_included_in_key(self):
        def my_func(service_id, only_active):
            pass

        gen = cache_key_generator("ns", my_func)
        key_false = gen("aaaaaaaa-1111-2222-3333-444444444444", False)
        key_true = gen("aaaaaaaa-1111-2222-3333-444444444444", True)
        assert key_false != key_true, "Boolean args must differentiate cache keys"

    def test_uuid_object_and_string_produce_same_key(self):
        def my_func(service_id):
            pass

        gen = cache_key_generator("ns", my_func)
        key_str = gen("aaaaaaaa-1111-2222-3333-444444444444")
        key_obj = gen(UUID("aaaaaaaa-1111-2222-3333-444444444444"))
        assert key_str == key_obj


class TestCacheOnArguments:
    def test_applies_dogpile_decorator_after_adding_group_metadata(self, mocker):
        captured = {}

        def dogpile_decorator(fn):
            captured["cache_group"] = fn.__cache_group__
            return fn

        mocked_cache_on_arguments = mocker.patch(
            "app.caching.dogpile_region.cache_on_arguments",
            return_value=dogpile_decorator,
        )

        @cache_on_arguments(namespace="service", group_by="service_id")
        def fetch_service(service_id):
            return service_id

        service_id = UUID("d4e5f6a7-1234-5678-9abc-def012345678")

        assert fetch_service(service_id) == service_id
        assert captured["cache_group"] == ("service", "service_id")
        mocked_cache_on_arguments.assert_called_once_with(namespace="service")


class TestJsonSerializer:
    def test_serializer_returns_bytes(self):
        payload = {"id": "abc-123", "active": True}
        serialized = _json_cache_serializer(payload)

        assert isinstance(serialized, bytes)

    def test_serializer_and_deserializer_roundtrip(self):
        payload = {"id": "abc-123", "active": True, "count": 2}
        serialized = _json_cache_serializer(payload)
        deserialized = _json_cache_deserializer(serialized)

        assert deserialized == payload


class TestInitDogpileCache:
    def test_uses_localhost_when_redis_url_is_none(self, mocker):
        app = Flask("test")
        app.config.update(REDIS_URL=None, DOGPILE_CACHE_EXPIRATION=600, DOGPILE_CACHE_BACKEND="dogpile.cache.redis")

        mock_configure = mocker.patch("app.caching.dogpile_region.configure")
        mocker.patch("app.caching.short_lived_region.configure")

        init_dogpile_cache(app)

        _, kwargs = mock_configure.call_args
        assert kwargs["arguments"]["url"] == "redis://localhost:6379/0"

    def test_short_lived_region_redis_ttl_tracks_freshness_window(self, mocker):
        app = mocker.MagicMock()
        app.config.get.side_effect = lambda key, default=None: {
            "REDIS_URL": "redis://cache:6379/0",
            "DOGPILE_CACHE_EXPIRATION": 600,
            "DOGPILE_SHORT_LIVED_CACHE_EXPIRATION": 30,
        }.get(key, default)
        mocker.patch("app.caching.dogpile_region.configure")
        mock_notification_configure = mocker.patch("app.caching.short_lived_region.configure")

        init_dogpile_cache(app)

        _, kwargs = mock_notification_configure.call_args
        assert kwargs["expiration_time"] == 30
        assert kwargs["arguments"]["url"] == "redis://cache:6379/0"
        assert kwargs["arguments"]["redis_expiration_time"] == 60
