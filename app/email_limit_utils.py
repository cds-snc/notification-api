from datetime import timedelta
from uuid import UUID

from flask import current_app
from notifications_utils.clients.redis import email_daily_count_cache_key

from app import redis_store
from app.dao.services_dao import fetch_todays_total_email_count


def fetch_todays_email_count(service_id: UUID) -> int:
    if not current_app.config["REDIS_ENABLED"]:
        return fetch_todays_total_email_count(service_id)

    cache_key = email_daily_count_cache_key(service_id)
    total_email_count = redis_store.get(cache_key)
    if total_email_count is None:
        total_email_count = fetch_todays_total_email_count(service_id)
        redis_store.set(cache_key, total_email_count, ex=int(timedelta(hours=2).total_seconds()))
    return int(total_email_count)


def increment_todays_email_count(service_id: UUID, increment_by: int) -> None:
    if not current_app.config["REDIS_ENABLED"]:
        return

    fetch_todays_email_count(service_id)  # to make sure it's set in redis
    cache_key = email_daily_count_cache_key(service_id)
    redis_store.incrby(cache_key, increment_by)
