import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import call
from uuid import UUID

from dogpile.cache import make_region
from dogpile.cache.api import NO_VALUE
from tests.app.db import create_service, create_template, create_user

from app import db
from app.cache import cache_events
from app.cache.cache_events import register_cache_orm_events
from app.cache.cache_invalidation_registry import CACHE_INVALIDATION_REGISTRY
from app.caching import (
    _json_cache_deserializer,
    _json_cache_serializer,
    cache_key_generator,
    cache_on_arguments,
    init_dogpile_cache,
)
from app.dao.permissions_dao import permission_dao
from app.dao.service_permissions_dao import (
    dao_add_service_permission,
    dao_remove_service_permission,
)
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


def _make_memory_region(expiration_time=600):
    return make_region(
        function_key_generator=cache_key_generator,
        serializer=_json_cache_serializer,
        deserializer=_json_cache_deserializer,
    ).configure(
        "dogpile.cache.memory",
        expiration_time=expiration_time,
    )


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

        mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

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

        mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

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

    def test_user_update_invalidates_user_cache(self, notify_db_session, mocker):
        register_cache_orm_events()
        user = create_user()
        mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

        save_model_user(user, update_dict={"name": "Updated name"})

        mocked_invalidate.assert_called_once_with("user", str(user.id))

    def test_permission_removal_rollback_discards_user_cache_invalidation(
        self, notify_db_session, sample_service, mocker
    ):
        register_cache_orm_events()
        user = sample_service.users[0]
        mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

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
        mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

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
        app = mocker.MagicMock()
        app.config.get.side_effect = lambda key, default=None: {
            "REDIS_URL": None,
            "DOGPILE_CACHE_EXPIRATION": 600,
            "DOGPILE_CACHE_BACKEND": "dogpile.cache.redis",
        }.get(key, default)

        mock_configure = mocker.patch("app.caching.dogpile_region.configure")

        init_dogpile_cache(app)

        _, kwargs = mock_configure.call_args
        assert kwargs["arguments"]["url"] == "redis://localhost:6379/0"
