from app import redis_store
from flask import current_app


def redis_check() -> str:
    if not redis_store.active:
        return 'Not Enabled'
    redis_client = redis_store.redis_store
    try:
        redis_client.ping()
    except Exception as ex:
        current_app.logger.error(ex)
        return 'FAILED'
    else:
        return 'OK'
