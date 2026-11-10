# Dogpile cache usage guide

Practical steps for working with the Dogpile cache. For the reasoning behind it, read the architecture guide first: [dogpile-cache-architecture-overview.md](./dogpile-cache-architecture-overview.md).

## Cache a DAO function

Decorate the function with `cache_on_arguments` ([app/caching.py:263](../../caching.py#L263)), naming the namespace and the argument that identifies the entity:

```python
from app.caching import cache_on_arguments

@cache_on_arguments(namespace="service", group_by="service_id")
def dao_fetch_service_by_id_cached(service_id: str, only_active=False) -> dict:
    query = Service.query.filter_by(id=service_id).options(joinedload("users"))
    ...
    return service_schema.dump(query.one())
```

Rules:

- Return JSON-serializable data (dictionaries, lists, strings, numbers), never ORM objects.
- `group_by` should name the function parameter whose value identifies the cache group.
- The namespace decides the key style, region and removal method. You do not choose them in the decorator.
- Use `should_cache_fn` to skip caching some results, for example `lambda value: value is not None` so misses are not cached.

### Expose it to callers

Keep a public DAO function that picks between the cache and the database, as `dao_fetch_service_by_id` does in [services_dao.py:217](../../dao/services_dao.py#L217):

- Only use the cached path when `FF_USE_DOGPILE_CACHING` is true and the caller passed `use_dogpile=True`.
- Catch `RedisError` from the cached call and fall back to the database.
- When `use_dogpile=True`, always return the same dictionary shape, even on the fallback path. Calls without it keep returning ORM objects.

## Add a new namespace

1. Decide how the namespace's cache entries will be invalidated. This is a choice between two strategies, and it also sets which region stores the entries. Declare it in `CACHE_NAMESPACES` ([app/caching.py:38](../../caching.py#L38)). Namespaces that are not listed get the default strategy.

   | | Prefix invalidation (default) | Exact-key invalidation |
   |---|---|---|
   | `CacheNamespace` setting | `key_strategy="prefix"`, `region="default"` | `key_strategy="exact"`, `region="short_lived"` |
   | Key | `<namespace>:<id>:<function>:<args>` | `<namespace>:<id>` |
   | Cached functions per entity | Any number, with any arguments | One, taking only the ID |
   | How entries are removed | Redis `SCAN` for the `<namespace>:<id>:` prefix, then delete | Batched `UNLINK` of the one known key, no scan |
   | Freshness | 600 s | 60 s (Redis keeps values for 120 s) |
   | Choose it for | Rarely changing entities (services, users, templates) | Frequently changing entities (notifications) |

   Choose exact keys when the entity changes so often that scanning Redis on every change is too costly. The short-lived region goes with it so that an entry that is missed by invalidation is only stale for a short time. Today only `notification` is declared this way; see `CacheNamespace` ([app/caching.py:23](../../caching.py#L23)) for the full definition.
2. If you chose exact keys, the namespace allows only one cached function per entity, and it must take only the `group_by` argument. Apply other filters to the returned data (see `dao_get_notification_snapshot_cached` in [notifications_dao.py:381](../../dao/notifications_dao.py#L381)).
3. Register the models that should clear it in [cache_invalidation_registry.py:48](../cache_invalidation_registry.py#L48) (the `Template` rule is shown):

```python
Template: [
    CacheInvalidationRule(namespace="template", entity_id_attribute="id"),
],
```

Set `invalidate_on_insert=False` ([cache_invalidation_registry.py:25](../cache_invalidation_registry.py#L25)) only when a new row cannot already be cached.

## Invalidate after bulk writes

Normal ORM changes (add, update, delete through the session) are tracked automatically. When you change an object, the session knows which row changed and the cache listeners can look up its ID.

A bulk write is different. It sends SQL straight to the database and never loads the rows as objects, so the session cannot tell which entities changed. You have to hand the cache the affected IDs yourself, or the old entries stay in Redis until they expire.

"Affected IDs" are the values the registry rules read from the model. Each rule in [cache_invalidation_registry.py:28](../cache_invalidation_registry.py#L28) has an `entity_id_attribute`, and you pass one keyword argument per attribute, using the same name. For example:

| Model | Keyword arguments to pass | Entries cleared |
|---|---|---|
| `User` | `id` | user |
| `Notification` | `id` | notification |
| `ServiceUser` | `service_id` **and** `user_id` | service and user |

If you leave out an attribute that a rule needs, the call raises `ValueError` rather than silently leaving one cache stale. Each value can be a single ID or a list of IDs.

Both options below clear the cache only after the transaction commits, and discard it on rollback.

### When you know the IDs before the statement runs

Wrap the statement with `cache_invalidating_dml` ([cache_dml.py:8](../cache_dml.py#L8)). This works for bulk `update` and `delete` statements. The real call in [users_dao.py:41](../../dao/users_dao.py#L41) updates one user:

```python
statement = update(User).where(User.id == usr.id).values(**updates).execution_options(synchronize_session="fetch")
db.session.execute(cache_invalidating_dml(statement, id=usr.id))
```

A bulk delete of a user's membership on a service must name both sides, because a `ServiceUser` change clears the service cache and the user cache:

```python
statement = delete(ServiceUser).where(ServiceUser.service_id == service_id, ServiceUser.user_id == user_id)
db.session.execute(cache_invalidating_dml(statement, service_id=service_id, user_id=user_id))
```

If a statement matches many rows, pass a list: `cache_invalidating_dml(statement, id=[id_1, id_2])`.

### When you only learn the IDs afterwards

Use `queue_cache_invalidations` ([cache_events.py:52](../cache_events.py#L52)) for `bulk_save_objects` or when the statement itself selects the rows. Collect the IDs first, then queue them. For example, `update_notification_statuses` ([notifications_dao.py:269](../../dao/notifications_dao.py#L269)) saves a list of objects in one call:

```python
db.session.bulk_save_objects(notifications)
queue_cache_invalidations(db.session, Notification, id=[notification.id for notification in notifications])
```

When one statement both changes and selects the rows, use `RETURNING` to get the IDs, as [jobs_dao.py:276](../../dao/jobs_dao.py#L276) does when cancelling a job:

```python
notification_ids = db.session.execute(
    update(Notification).where(Notification.job_id == job.id).values(...).returning(Notification.id)
).scalars().all()
queue_cache_invalidations(db.session, Notification, id=notification_ids)
```

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `FF_USE_DOGPILE_CACHING` | `False` | Env flag. Turns on the cached path for opted-in DAO calls. |
| `DOGPILE_CACHE_EXPIRATION` | `600` | Default region freshness and Redis lifetime, in seconds. |
| `DOGPILE_SHORT_LIVED_CACHE_EXPIRATION` | `60` | Short-lived region freshness, in seconds. Redis keeps values for twice this. |
| `DOGPILE_CACHE_BACKEND` | `dogpile.cache.redis` | Dogpile backend. |

Redis uses `REDIS_URL`. Both regions are set up in `init_dogpile_cache` ([app/caching.py:355](../../caching.py#L355)).


## Testing

- Cache tests live in `tests/app/cache/`: `test_cache.py` (keys, regions, decorator) and `test_cache_events.py` (invalidation events).
- Patch the module-level regions or the Redis client rather than relying on a live Redis for unit tests.
- When you add a registry rule, add a test in `tests/app/cache/test_cache_events.py` showing the rule queues the expected namespace and ID.
- When you add a cached DAO function, test both the cached path and the Redis-error fallback returning the same shape.

## Metrics

Emitted through statsd:

- `cache.access.<namespace>.<reused|regenerated|error>`, plus `.duration`: how each read was served.
- `cache.creator.<namespace>.<success|error>.duration`: time spent loading from the database on a miss.
- `cache.invalidation.<namespace>.<success|error>`, plus `.duration`, `.scans`, `.matched`, `.deleted`: prefix invalidation work.


### Detailed metrics breakdown

| Metric | Type | Meaning |
| --- | --- | --- |
| `dao.execution_time.<module>.<function>` | Timer | Duration of a DAO decorated with `log_execution_time`, including failing calls. |
| `cache.access.<namespace>.reused` | Counter | Calls that returned without executing the creator. |
| `cache.access.<namespace>.regenerated` | Counter | Successful calls that executed the creator. |
| `cache.access.<namespace>.error` | Counter | Cached calls that raised an exception. |
| `cache.access.<namespace>.<outcome>.duration` | Timer | Complete cached-call duration, separated by outcome. |
| `cache.invalidation.<namespace>.success` | Counter | Successfully completed prefix invalidations. |
| `cache.invalidation.<namespace>.error` | Counter | Failed prefix invalidations. |
| `cache.invalidation.<namespace>.<outcome>.duration` | Timer | Invalidation duration, separated into success/error. |
| `cache.invalidation.<namespace>.scans` | Counter | Completed Redis SCAN calls. |
| `cache.invalidation.<namespace>.matched` | Counter | Keys returned by completed scans. |
| `cache.invalidation.<namespace>.deleted` | Counter | Keys confirmed deleted by Redis. |
| `cache.collect_invalidations.success` | Counter | Successfully completed ORM invalidation collection passes. |
| `cache.collect_invalidations.error` | Counter | Failed ORM invalidation collection passes. |
| `cache.collect_invalidations.<outcome>.duration` | Timer | Collection duration, separated into success/error. |
| `cache.collect_invalidations.instances` | Counter | ORM instances examined during collection passes. |
| `cache.collect_invalidations.invalidations` | Counter | Newly queued targets after deduplication within the transaction. |

A cloudwatch dashboard named `Notify-Dogpile-{staging|production}` is available with analysis and charts based on these metrics.  