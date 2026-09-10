# app/cache/cache_dml.py

_CACHE_INVALIDATION_ENTITY_IDS_OPTION = (
    "notify_cache_invalidation_entity_ids"
)


def cache_invalidating_dml(statement, **entity_ids):
    return statement.execution_options(
        **{_CACHE_INVALIDATION_ENTITY_IDS_OPTION: entity_ids}
    )