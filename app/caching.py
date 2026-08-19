import inspect
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


def _bind_args(fn, args, kwargs):
    sig = inspect.signature(fn)
    bound = sig.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    return bound.arguments


def cache_key_generator(namespace, fn):
    """Generate a cache key from namespace, function name, and argument list values e.g:

    ```
    service
    |
    +--> service:dao_fetch_service_by_id_cached|<service_id>|other|args|here
    ```

    UUIDs are normalized to their string form so that UUID objs resolve to the same cache key.
    """
    fn_name = fn.__name__
    group_info = GROUP_BY_FUNCTION.get(fn_name)

    def generate_key(*args, **kwargs):
        bound = _bind_args(fn, args, kwargs)

        if group_info:
            group_name, primary_param_key = group_info
            primary_value = _as_uuid_string(bound.get(primary_param_key, "missing"))
        else:
            group_name, primary_value = "ungrouped", "none"

        arg_fingerprint = "|".join(f"{name}={_as_uuid_string(value)}" for name, value in bound.items())
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
    prefix = f"{ns}:{group_name}:{group_id}:"
    cursor = 0
    deleted = 0

    while True:
        cursor, keys = redis_client.scan(cursor=cursor, match=f"{prefix}*", count=batch_size)
        if keys:
            deleted += redis_client.delete(*keys)
        if cursor == 0:
            break

    return deleted


dogpile_region = make_region(
    function_key_generator=cache_key_generator,
)


def init_dogpile_cache(app):
    redis_url = app.config.get("REDIS_URL", "redis://localhost:6379/0")
    expiration_time = app.config.get("DOGPILE_CACHE_EXPIRATION", 600)

    dogpile_region.configure(
        backend=app.config.get("DOGPILE_CACHE_BACKEND", "dogpile.cache.redis"),
        expiration_time=expiration_time,
        arguments={
            "url": redis_url,
            "redis_expiration_time": expiration_time,
            "distributed_lock": True,
            "thread_local_lock": False,
            "lock_timeout": 5,
        },
    )
