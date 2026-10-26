# Dogpile cache usage guide (WIP - will evolve along with implementation)

This guide explains how to add a cached DAO read and keep it consistent when
the underlying data changes. For the design and transaction lifecycle, see
[Dogpile cache architecture](dogpile-cache-architecture.md).

## Before adding a cached read

Identify:

1. The entity that owns the cached result, such as a service, user, or template.
2. Every ORM model whose writes can change that result.
3. Every write path for those models, including direct SQLAlchemy `UPDATE` and
   `DELETE` statements.

The cache is read-through. A miss executes the DAO function and stores its
result; a hit returns the stored result. The database remains the source of
truth, so every relevant successful write must invalidate the cached group.

## Using the cache decorator

Import and apply the application's cache wrapper:

```python
from app.caching import cache_on_arguments


@cache_on_arguments(namespace="service", group_by="service_id")
def dao_fetch_service_by_id_cached(service_id: str, only_active=False) -> dict:
    service = Service.query.filter_by(id=service_id).one()
    return service_schema.dump(service)
```

`namespace` identifies the kind of cache owner. `group_by` must be the name of
a function argument containing that owner's ID. The generated keys begin with:

```text
<namespace>:<group-id>:
```

All other arguments are included in the key fingerprint. This permits several
argument combinations in one group and allows a write to invalidate the
entire group.

Choose the group owner based on what should invalidate all variants. 

```python
@cache_on_arguments(namespace="template", group_by="template_id")
def dao_get_template_by_id_cached(template_id, service_id) -> dict:
    template = dao_get_template_by_id_and_service_id(template_id, service_id)
    return template_schema.dump(template)
```

### Requirements and cautions

- Return JSON-serializable values such as dictionaries, lists, strings,
  numbers, ect. Do not cache SQLAlchemy model instances.
- Use a stable entity ID as `group_by`; the named argument must exist in the
  decorated function's signature.
- Include query options that can change the result as function arguments. They
  become part of the cache fingerprint automatically.
- Use the same namespace in the decorator and the corresponding invalidation
  registry rules.

## Using and updating the invalidation registry

`CACHE_INVALIDATION_REGISTRY` in
`app/cache/cache_invalidation_registry.py` maps a changed ORM model to the
cache groups affected by that change:

```python
ServiceUser: [
    CacheInvalidationRule(namespace="service", entity_id_attribute="service_id"),
    CacheInvalidationRule(namespace="user", entity_id_attribute="user_id"),
]
```

Each rule has two fields:

- `namespace`: the cached namespace to invalidate.
- `entity_id_attribute`: a direct attribute on the changed model containing the
  cache owner's ID.

For ordinary ORM changes, the event listeners: 
- Inspect new, dirty, and deleted instances after flush. 
- They read the configured attributes and queue each `(namespace, entity ID)` pair. 
- The groups are deleted from Redis only after a
successful commit 
- A rollback discards the queued invalidations.

### When to add or update a rule

Add a registry entry when a write to a model can change a cached payload. This
includes related models whose fields are serialized into the payload. For
example, changing `TemplateRedacted` affects a cached template even though the
`Template` row itself may not change:

```python
TemplateRedacted: [
    CacheInvalidationRule(
        namespace="template",
        entity_id_attribute="template_id",
    ),
]
```

Add multiple rules when one changed row affects multiple owners. A
`ServiceUser` change affects both the service and user cache groups, so both IDs
must be represented.


When changing the registry:
1. Confirm that every rule's `entity_id_attribute` exists on the mapped model.
2. Confirm that its `namespace` exactly matches the cached DAO decorator.
3. Review create, update, and delete paths for the model.
4. Update the registry assertions and commit/rollback invalidation tests in
   `tests/app/cache/test_cache_events.py`.
5. Check bulk DML paths for all attributes required by the model's rules.

## When not to use the registry

Use registry rules only when the model has a direct attribute identifying the
cache owner. If determining affected owners requires a query, unusual fan-out,
or domain-specific logic, queue invalidation explicitly in the method that
already knows those owners rather than hiding that logic in the registry.

For example, 

Changing a `TemplateCategory` can change the `process_type` of every template assigned 
to that category. A `TemplateCategory` has its own `id`, but is associated with many 
`Templates` that could be used in a registry rule. Mapping its `id` to the `template` 
namespace would incorrectly invalidate `template:<category-id>:*` instead of the cache
groups belonging to the affected templates.

The category update operation instead finds the IDs of the templates using
that category and queue one `("template", template_id)` invalidation for each
of them. This fan-out belongs in the operation because it understands the
category-to-template relationship and can collect the IDs within the same
transaction.

> TODO: expose and document a public helper for queuing an arbitrary invalidation.

## Wrapping DML with `cache_invalidating_dml`

Normal mutations made against models loaded into the SQLAlchemy session are discovered automatically:

```python
service.name = "New name"
db.session.add(service)
db.session.commit()
```

However, direct `UPDATE` and `DELETE` statements bypass changed-instance tracking. Wrap
these statements with `cache_invalidating_dml` and supply the entity IDs named
by the target model's registry rules:

```python
from sqlalchemy import delete

from app.cache.cache_dml import cache_invalidating_dml


statement = delete(ServicePermission).where(
    ServicePermission.service_id == service_id,
    ServicePermission.permission == permission,
)
result = db.session.execute(
    cache_invalidating_dml(statement, service_id=service_id)
)
db.session.commit()
```

The keyword names passed to `cache_invalidating_dml` must match the registry's
`entity_id_attribute` values, not necessarily the SQL filter parameter names.
For a model with more than one required attribute, provide all of them:

```python
statement = delete(ServiceUser).where(
    ServiceUser.service_id == service_id,
    ServiceUser.user_id == user_id,
)
db.session.execute(
    cache_invalidating_dml(
        statement,
        service_id=service_id,
        user_id=user_id,
    )
)
```

An ID value may be a UUID, string, or collection of IDs. Collections
are useful when one statement affects several known cache owners:

```python
db.session.execute(
    cache_invalidating_dml(statement, user_id=user_ids)
)
```

### When wrapping is required

Wrap a statement when all of the following are true:

- It is a SQLAlchemy ORM `UPDATE` or `DELETE` executed with
  `db.session.execute(...)`.
- Its mapped model appears in the `CACHE_INVALIDATION_REGISTRY`.
- The affected owner IDs are known by the caller.

Avoid legacy `Query.update()` and `Query.delete()` for registered models. They
these methods are legacy 1.x SQLAlchemy APIs and do not provide the necessary 
execution metadata to automatically handle cache invalidation. Replace them 
with modern `update(Model)` or `delete(Model)` statements executed through
the session and wrapped with `cache_invalidating_dml`.

## Cache performance metrics

DAO timings, cached reads, ORM invalidation collection, and prefix invalidation
emit StatsD metrics instead of per-call performance logs. Metrics use the
configured StatsD client and are sent when `STATSD_ENABLED` is enabled. The
client adds its environment/application prefix to the names below. Duration
values are milliseconds. Failure diagnostics retain their exception/error logs.

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

Namespaces are `service`, `template`, and `user`. No entity IDs or cache keys
are included in metric names. Invalidation counts include completed work before
an error, if any. The original exceptions still propagate.

The `log_execution_time` decorator keeps its existing name for compatibility but
now sends a StatsD timer, not a log record. Cached DAOs are already measured by
`cache_on_arguments` and should not also use this decorator. Collection counters
cover work performed before commit, including transactions that later roll back;
they are not counts of completed Redis deletions. Post-commit invalidation
failures remain logged and do not undo the committed database transaction.

The former `dao.execution_time`, `cache.collect_invalidations`, and
`cache.invalidate_group_keys` performance log messages are no longer emitted.
CloudWatch Logs Insights queries for those messages will only return historical
records from before this change.

To evaluate cache performance:

- Calculate reuse percentage from the reused count divided by all three read
  outcome counts over the same interval. `reused` includes stale values served
  during concurrent regeneration, so this is not a strict fresh-hit rate.
- Compare reused and regenerated duration distributions for each namespace.
  The timer covers key generation, Redis operations, lock waiting, and creator
  execution/serialization when applicable; it does not isolate those stages.
- Compare regeneration spikes with invalidation rates and deleted-key counts.
- Track read and invalidation errors separately.
- Compare equivalent request-level latency and database load with the feature
  flag off/on under the same workload. DAO timings alone have different
  serialization boundaries and cannot establish the overall request benefit.

The StatsD receiver determines where these metrics can be graphed. Emitting
StatsD metrics does not automatically create CloudWatch custom metrics.

## Implementation checklist

- Add a cached DAO returning a JSON-safe value.
- Set `namespace` and `group_by` to the cache owner's namespace and ID argument.
- Ensure that the model <-> Cache mappings in `CACHE_INVALIDATION_REGISTRY` are up to date.
- Wrap every relevant direct `UPDATE` and `DELETE` with
  `cache_invalidating_dml` and use modern `update(model)` / `delete(model)` calls.
- Test cache hits and misses, key grouping, successful-commit invalidation, and
  rollback behavior.