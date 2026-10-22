import inspect
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from time import perf_counter
from uuid import UUID

from dogpile.cache import make_region

logger = logging.getLogger(__name__)

KEY_STRATEGY_PREFIX = "prefix"
KEY_STRATEGY_EXACT = "exact"
REGION_DEFAULT = "default"
REGION_SHORT_LIVED = "short_lived"


@dataclass(frozen=True)
class CacheNamespace:
    """How a namespace's keys are built, which region stores them, and therefore how they are invalidated.

    - ``prefix``: ``<namespace>:<id>:<fn>:<args>``. Any number of cached functions and argument
      variants per entity; invalidated with a Redis SCAN on ``<namespace>:<id>:``. Best for
      low-churn entities (services, users, templates).
    - ``exact``: ``<namespace>:<id>``. One cached function per entity that takes only the ID;
      invalidated with a batched UNLINK and no SCAN. Best for high-churn entities.
    """

    key_strategy: str = KEY_STRATEGY_PREFIX
    region: str = REGION_DEFAULT


# The single place a namespace's caching behaviour is declared. Namespaces not listed use the defaults.
CACHE_NAMESPACES: dict[str, CacheNamespace] = {
    "notification": CacheNamespace(key_strategy=KEY_STRATEGY_EXACT, region=REGION_SHORT_LIVED),
}


def get_cache_namespace(namespace: str) -> CacheNamespace:
    return CACHE_NAMESPACES.get(namespace, CacheNamespace())


def _as_uuid_string(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        try:
            return str(UUID(value))
        except ValueError:
            return None
    return None


def _serialize_key_value(value):
    """Custom key value serializer to go along with the custom key generator

    Normally dogpile would serialize these values for us but we implement a custom key gen
    strategy so we must handle this serialization ourselves.
    """
    normalized_uuid = _as_uuid_string(value)
    if normalized_uuid is not None:
        return normalized_uuid

    if value is None:
        return "None"

    if isinstance(value, (bool, int, float, str)):
        return str(value)

    if isinstance(value, tuple):
        return f"({','.join(_serialize_key_value(item) for item in value)})"

    if isinstance(value, list):
        return f"[{','.join(_serialize_key_value(item) for item in value)}]"

    if isinstance(value, set):
        serialized_items = sorted(_serialize_key_value(item) for item in value)
        return f"{{{','.join(serialized_items)}}}"

    if isinstance(value, dict):
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        except TypeError:
            serialized_items = sorted((str(k), _serialize_key_value(v)) for k, v in value.items())
            return repr(serialized_items)

    return repr(value)


def _json_cache_serializer(value):
    # Key order is preserved (not sorted) so cached API payloads are byte-identical to uncached responses.
    # Deterministic ordering only matters for cache keys, which _serialize_key_value handles.
    return json.dumps(value, default=str, separators=(",", ":")).encode("utf-8")


def _json_cache_deserializer(value):
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value)


def _bind_args(fn, args, kwargs):
    sig = inspect.signature(fn)
    bound = sig.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    return bound.arguments


def cache_key_generator(namespace, fn):
    """Generate a cache key from namespace, function name, and argument list values

    Example:
    ```
    service
    |
    +--> <service_id>
    |
    +----> <dao_fn_name>
    |
    +------> service:<id>:<dao_fn_name>:fn_param|fn_param|...
    ```

    Namespaces using the ``exact`` key strategy produce ``<namespace>:<id>`` instead.

    UUIDs are normalized to their string form so that UUID objs resolve to the same cache key.
    Other argument types are serialized deterministically to avoid collisions.
    """
    fn_name = fn.__name__
    group_info = getattr(fn, "__cache_group__", None)
    is_exact = get_cache_namespace(namespace).key_strategy == KEY_STRATEGY_EXACT

    def generate_key(*args, **kwargs):
        bound = _bind_args(fn, args, kwargs)

        if group_info:
            _, primary_param_key = group_info
            if is_exact:
                return exact_cache_key(namespace, bound[primary_param_key])
            primary_value = _serialize_key_value(bound.get(primary_param_key, "missing"))

            # Keep grouped keys compact and invalidateable by service/user id prefix.
            arg_fingerprint = "|".join(
                f"{name}={_serialize_key_value(value)}" for name, value in bound.items() if name != primary_param_key
            )
            return f"{namespace}:{primary_value}:{fn_name}:{arg_fingerprint}"
        else:
            group_name, primary_value = "ungrouped", "none"

        arg_fingerprint = "|".join(f"{name}={_serialize_key_value(value)}" for name, value in bound.items())
        return f"{namespace}:{group_name}:{primary_value}:{fn_name}:{arg_fingerprint}"

    return generate_key


def _get_region(name):
    # Resolved at call time so tests can patch the module-level regions.
    return {REGION_DEFAULT: dogpile_region, REGION_SHORT_LIVED: short_lived_region}[name]


def _get_redis_client_from_region(region=None):
    backend = (region or dogpile_region).backend
    client = getattr(backend, "writer_client", None) or getattr(backend, "client", None)

    if client is None:
        raise RuntimeError("Dogpile region is not using a Redis backend client or the region has not yet been initialized")
    return client


def exact_cache_key(namespace, entity_id):
    return f"{namespace}:{_serialize_key_value(entity_id)}"


def _unlink_exact_keys(namespace, entity_ids, region, batch_size=500):
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    keys = list(dict.fromkeys(exact_cache_key(namespace, entity_id) for entity_id in entity_ids))

    if not keys:
        return 0

    redis_client = _get_redis_client_from_region(region)
    deleted = 0
    batches = 0
    started = perf_counter()

    try:
        for offset in range(0, len(keys), batch_size):
            batches += 1
            deleted += redis_client.unlink(*keys[offset : offset + batch_size])
    finally:
        elapsed_ms = (perf_counter() - started) * 1000
        logger.info(
            f"cache.invalidate_exact_keys namespace={namespace} batch_size={batch_size} batches={batches} "
            f"keys={len(keys)} deleted={deleted} elapsed_ms={elapsed_ms:.2f}"
        )
    return deleted


def invalidate_cache_entities(namespace, entity_ids) -> None:
    """Invalidate every cached entry for the given entities, using the namespace's key strategy."""
    config = get_cache_namespace(namespace)
    if config.key_strategy == KEY_STRATEGY_EXACT:
        _unlink_exact_keys(namespace, entity_ids, _get_region(config.region))
        return
    for entity_id in dict.fromkeys(entity_ids):
        invalidate_group_keys(namespace, entity_id)


def invalidate_group_keys(group_name, group_id, batch_size=500, namespace=None):
    started = perf_counter()
    ns = namespace or group_name
    # Grouped keys are generated as <namespace>:<group_id>:<function>:<fingerprint>
    prefix = f"{ns}:{group_id}:"
    cursor = 0
    deleted = 0
    matched = 0
    scans = 0

    try:
        redis_client = _get_redis_client_from_region(_get_region(get_cache_namespace(ns).region))
        while True:
            cursor, keys = redis_client.scan(cursor=cursor, match=f"{prefix}*", count=batch_size)
            scans += 1
            matched += len(keys)
            if keys:
                deleted += redis_client.delete(*keys)
            if cursor == 0:
                break
    finally:
        elapsed_ms = (perf_counter() - started) * 1000
        logger.info(
            f"cache.invalidate_group_keys namespace={ns} batch_size={batch_size} scans={scans} "
            f"matched={matched} deleted={deleted} elapsed_ms={elapsed_ms:.2f}"
        )

    return deleted


def invalidate_service_cache_keys(service_id):
    """Cypress helper method. Invalidate all dogpile cache entries associated with a service id.

    This invalidates the exact service fetch keys and then best-effort clears
    all grouped service keys for the id prefix.
    """
    normalized_service_id = str(service_id)

    # Prefix invalidation is best-effort and requires Redis backend access.
    try:
        invalidate_group_keys("service", normalized_service_id)
    except Exception:
        pass  #  Failures are swallowed because request/transaction paths should not fail due to cache backend issues.


def cache_on_arguments(*, namespace, group_by, should_cache_fn=None):
    """Cache function arguments and group its keys by one named argument.

    Key format, storage region and invalidation are derived from the namespace's entry in
    ``CACHE_NAMESPACES``; callers never choose them, so they cannot drift out of sync.
    ``should_cache_fn`` is passed to dogpile (e.g. ``lambda value: value is not None``).
    """
    config = get_cache_namespace(namespace)

    def decorate(fn):
        params = list(inspect.signature(fn).parameters)
        if group_by not in params:
            raise TypeError(f"{fn.__qualname__} must accept the group_by argument '{group_by}'")
        if config.key_strategy == KEY_STRATEGY_EXACT and params != [group_by]:
            raise TypeError(
                f"{fn.__qualname__}: namespace '{namespace}' uses exact keys ('{namespace}:<{group_by}>'), so the "
                f"cached function must take only '{group_by}'. Apply other filters (service, key type) to the result."
            )
        fn.__cache_group__ = (namespace, group_by)
        invocation: ContextVar[dict[str, bool] | None] = ContextVar(f"cache_access_{namespace}_{fn.__name__}", default=None)

        @wraps(fn)
        def creator(*args, **kwargs):
            state = invocation.get()
            if state is not None:
                state["creator_executed"] = True
            return fn(*args, **kwargs)

        options = {"namespace": namespace}
        if should_cache_fn is not None:
            options["should_cache_fn"] = should_cache_fn
        cached_fn = _get_region(config.region).cache_on_arguments(**options)(creator)

        @wraps(cached_fn)
        def wrapper(*args, **kwargs):
            state = {"creator_executed": False}
            token = invocation.set(state)
            started = perf_counter()
            outcome = "error"
            try:
                result = cached_fn(*args, **kwargs)
                outcome = "regenerated" if state["creator_executed"] else "reused"
                return result
            finally:
                elapsed_ms = (perf_counter() - started) * 1000
                invocation.reset(token)
                logger.info(
                    f"dao.execution_time function={fn.__module__}.{fn.__qualname__} elapsed_ms={elapsed_ms:.2f} "
                    f"cache_namespace={namespace} cache_outcome={outcome}"
                )

        return wrapper

    return decorate


dogpile_region = make_region(
    function_key_generator=cache_key_generator,
    serializer=_json_cache_serializer,
    deserializer=_json_cache_deserializer,
)

# For high-churn entities: a short freshness window bounds staleness when invalidation misses a write.
short_lived_region = make_region(
    function_key_generator=cache_key_generator,
    serializer=_json_cache_serializer,
    deserializer=_json_cache_deserializer,
)


def _configure_region(region, app, redis_url, expiration_time, redis_expiration_time):
    region.configure(
        backend=app.config.get("DOGPILE_CACHE_BACKEND", "dogpile.cache.redis"),
        expiration_time=expiration_time,
        replace_existing_backend=True,
        arguments={
            "url": redis_url,
            "redis_expiration_time": redis_expiration_time,
            "distributed_lock": True,
            "thread_local_lock": False,
            "lock_timeout": 5,
        },
    )


def init_dogpile_cache(app):
    # Module loggers do not inherit handlers from Flask's "api" or "celery" logger.
    for name in (__name__, "app.cache.cache_events"):
        cache_logger = logging.getLogger(name)
        cache_logger.handlers = app.logger.handlers[:]
        cache_logger.setLevel(app.logger.getEffectiveLevel())
        cache_logger.propagate = False
        
    redis_url = app.config.get("REDIS_URL") or "redis://localhost:6379/0"
    expiration_time = app.config.get("DOGPILE_CACHE_EXPIRATION", 600)
    _configure_region(dogpile_region, app, redis_url, expiration_time, expiration_time)

    short_lived_expiration = app.config.get("DOGPILE_SHORT_LIVED_CACHE_EXPIRATION", 60)
    # Redis keeps values one extra window so an expired value can be served while a single worker regenerates it.
    _configure_region(short_lived_region, app, redis_url, short_lived_expiration, short_lived_expiration * 2)
