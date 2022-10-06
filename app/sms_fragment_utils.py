from datetime import timedelta
from notifications_utils.clients.redis import sms_daily_count_cache_key
from flask import current_app
from app.dao.services_dao import fetch_todays_total_sms_count
from app import redis_store


def fetch_daily_sms_fragment_count(service_id):
    if current_app.config["REDIS_ENABLED"]:
        cache_key = sms_daily_count_cache_key(service_id)
        fragment_count = redis_store.get(cache_key)
        if fragment_count is None:
            fragment_count = fetch_todays_total_sms_count(service_id)
            redis_store.set(cache_key, fragment_count, ex=int(timedelta(hours=2).total_seconds()))
        return int(fragment_count)
    else:
        return fetch_todays_total_sms_count(service_id)


def increment_daily_sms_fragment_count(service_id, increment_by):
    if current_app.config["REDIS_ENABLED"]:
        fetch_daily_sms_fragment_count(service_id)  # make sure it's set in redis
        cache_key = sms_daily_count_cache_key(service_id)
        redis_store.incrby(cache_key, increment_by)


def delete_daily_sms_fragment_count(service_id):
    if current_app.config["REDIS_ENABLED"]:
        cache_key = sms_daily_count_cache_key(service_id)
        redis_store.delete(cache_key)
