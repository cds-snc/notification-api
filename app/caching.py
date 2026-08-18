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
    """Basic cache key generator, parents keys in the specified dogpile namespace
    and formats like so: `dao_function_name_being_cached-primary_entity_id` e.g

    ```
    service
    |
    +--> service:dao_fetch_service_by_id_cached-<service_id>
    ```

    This is rudimentary for now as it operates under the assumption that the first
    uuid-like value encountered maps 1:1 with the primary entity being fetched which
    may not be true across the codebase.
    """
    fname = fn.__name__

    def generate_key(*args):
        for value in args:
            id = _uuidish(value)
            if id:
                primary_id = id
                break

        return f"{namespace}:{fname}-{primary_id}"

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
