from notifications_utils.clients.redis.redis_client import RedisClient, prepare_value

from time import time
from flask import current_app


def is_rate_limit_exceeded(redis_client: RedisClient, cache_key, limit, interval, raise_exception=False):
    cache_key = prepare_value(cache_key)
    if redis_client.active:
        try:
            pipe = redis_client.redis_store.pipeline()
            when = time()
            pipe.zremrangebyscore(cache_key, '-inf', when - interval)
            pipe.zcard(cache_key)
            pipe.expire(cache_key, interval)
            result = pipe.execute()

            return result[2] > limit

        except Exception as e:
            handle_exception(e, raise_exception, 'rate-limit-pipeline', cache_key)
            return False
    else:
        return False


def update_redis_cache_key_for(redis_client: RedisClient, cache_key: str, raise_exception=False):
    cache_key = prepare_value(cache_key)
    if redis_client.active:
        try:
            pipe = redis_client.redis_store.pipeline()
            when = time()
            pipe.zadd(cache_key, {when: when})
            pipe.execute()
        except Exception as e:
            handle_exception(e, raise_exception, 'rate-limit-pipeline', cache_key)
            return False


def handle_exception(e, raise_exception, operation, key_name):
    current_app.logger.exception('Redis error performing {} on {}'.format(operation, key_name))
    if raise_exception:
        raise e
