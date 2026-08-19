from uuid import UUID

from dogpile.cache import make_region


def _uuidish(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        try:
            return str(UUID(value))
        except ValueError:
            return None
    return None


def cache_key_generator(namespace, fn, **kw):
    """Generate a cache key from namespace, function name, and argument list values e.g:

    ```
    service
    |
    +--> service:dao_fetch_service_by_id_cached|<service_id>|other|args|here
    ```

    UUIDs are normalized to their string form so that UUID objs resolve to the same cache key.
    """
    fname = fn.__name__

    def generate_key(*args):
        parts = []
        for value in args:
            normalized = _uuidish(value)
            parts.append(normalized if normalized else str(value))
        suffix = "|".join(parts)
        return f"{namespace}:{fname}|{suffix}" if suffix else f"{namespace}:{fname}"

    return generate_key


dogpile_region = make_region(function_key_generator=cache_key_generator)


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
