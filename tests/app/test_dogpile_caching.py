"""Tests for dogpile.cache eviction strategies.

These tests use the in-memory backend so they don't require a running Redis
instance.  The memory backend is single-process but exercises the same
CacheRegion API surface (get, set, invalidate, expiration) that the Redis
backend does in production.
"""

import time

from dogpile.cache import make_region
from dogpile.cache.api import NO_VALUE

from app.caching import _json_cache_deserializer, _json_cache_serializer, cache_key_generator


def _make_memory_region(expiration_time=600):
    """Create a throwaway in-memory region for a single test."""
    return make_region(function_key_generator=cache_key_generator).configure(
        "dogpile.cache.memory",
        expiration_time=expiration_time,
    )


class TestExpirationEviction:
    """Values should be considered stale after the configured expiration_time."""

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

        assert call_count == 2, "Each unique key should trigger exactly one creator call"


class TestExplicitInvalidation:
    """Calling .invalidate() on a decorated function should force regeneration."""

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

        fetch("aaaaaaaa-1111-2222-3333-444444444444")  # should regenerate
        fetch("bbbbbbbb-1111-2222-3333-444444444444")  # should still be cached

        assert call_count == 3, "Only the invalidated key should regenerate"


class TestRegionInvalidation:
    """region.invalidate() makes *all* keys stale in one call."""

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

        # Soft invalidation: dogpile returns the stale value to the first
        # caller while regenerating.
        fetch("abc-123")
        # After soft invalidation the region regenerates on next access
        assert call_count == 2


class TestDecoratorHelpers:
    """The decorator attaches .set(), .get(), .refresh() helpers."""

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
    """region.delete() removes a key entirely so the next get returns NO_VALUE."""

    def test_delete_removes_cached_value(self):
        region = _make_memory_region(expiration_time=600)

        region.set("mykey", "hello")
        assert region.get("mykey") == "hello"

        region.delete("mykey")
        assert region.get("mykey") is NO_VALUE


class TestCacheKeyGenerator:
    """Verify our custom key generator produces deterministic, namespaced keys."""

    def test_key_contains_namespace_and_function_name(self):
        def dao_fetch_service_by_id_cached(service_id):
            pass

        gen = cache_key_generator("service", dao_fetch_service_by_id_cached)
        key = gen("d4e5f6a7-1234-5678-9abc-def012345678")

        assert "service:" in key
        assert "dao_fetch_service_by_id_cached" in key
        assert "d4e5f6a7-1234-5678-9abc-def012345678" in key

    def test_grouped_key_uses_compact_prefix_and_excludes_primary_param_from_fingerprint(self):
        def dao_fetch_service_by_id_cached(service_id, only_active=False):
            pass

        gen = cache_key_generator("service", dao_fetch_service_by_id_cached)
        key = gen("d4e5f6a7-1234-5678-9abc-def012345678", False)

        assert key.startswith("service:d4e5f6a7-1234-5678-9abc-def012345678:dao_fetch_service_by_id_cached:")
        assert "only_active=False" in key
        assert "service_id=" not in key

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
        from uuid import UUID

        def my_func(service_id):
            pass

        gen = cache_key_generator("ns", my_func)
        key_str = gen("aaaaaaaa-1111-2222-3333-444444444444")
        key_obj = gen(UUID("aaaaaaaa-1111-2222-3333-444444444444"))
        assert key_str == key_obj


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
