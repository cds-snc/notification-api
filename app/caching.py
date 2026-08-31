import inspect
import json
from uuid import UUID

from dogpile.cache import make_region

GROUP_BY_FUNCTION = {
    "dao_fetch_service_by_id_cached": ("service", "service_id"),
    "dao_get_user_by_id_cached": ("user", "user_id"),
}


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
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")


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

    UUIDs are normalized to their string form so that UUID objs resolve to the same cache key.
    Other argument types are serialized deterministically to avoid collisions.
    """
    fn_name = fn.__name__
    group_info = GROUP_BY_FUNCTION.get(fn_name)

    def generate_key(*args, **kwargs):
        bound = _bind_args(fn, args, kwargs)

        if group_info:
            _, primary_param_key = group_info
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


def _get_redis_client_from_region():
    backend = dogpile_region.backend
    client = getattr(backend, "writer_client", None) or getattr(backend, "client", None)

    if client is None:
        raise RuntimeError("Dogpile region is not using a Redis backend client or the region has not yet been initialized")
    return client


def invalidate_group_keys(group_name, group_id, batch_size=500, namespace=None):
    ns = namespace or group_name
    redis_client = _get_redis_client_from_region()
    # Grouped keys are generated as <namespace>:<group_id>:<function>:<fingerprint>
    prefix = f"{ns}:{group_id}:"
    cursor = 0
    deleted = 0

    while True:
        cursor, keys = redis_client.scan(cursor=cursor, match=f"{prefix}*", count=batch_size)
        if keys:
            deleted += redis_client.delete(*keys)
        if cursor == 0:
            break

    return deleted


def invalidate_service_cache_keys(service_id):
    """Invalidate all dogpile cache entries associated with a service id.

    This invalidates the exact service fetch keys and then best-effort clears
    all grouped service keys for the id prefix.
    """
    normalized_service_id = str(service_id)

    # Prefix invalidation is best-effort and requires Redis backend access.
    try:
        invalidate_group_keys("service", normalized_service_id)
    except Exception:
        pass  #  Failures are swallowed because request/transaction paths should not fail due to cache backend issues.

      
dogpile_region = make_region(
    function_key_generator=cache_key_generator,
    serializer=_json_cache_serializer,
    deserializer=_json_cache_deserializer,
)


def init_dogpile_cache(app):
    redis_url = app.config.get("REDIS_URL") or "redis://localhost:6379/0"
    expiration_time = app.config.get("DOGPILE_CACHE_EXPIRATION", 600)

    dogpile_region.configure(
        backend=app.config.get("DOGPILE_CACHE_BACKEND", "dogpile.cache.redis"),
        expiration_time=expiration_time,
        replace_existing_backend=True,
        arguments={
            "url": redis_url,
            "redis_expiration_time": expiration_time,
            "distributed_lock": True,
            "thread_local_lock": False,
            "lock_timeout": 5,
        },
    )
