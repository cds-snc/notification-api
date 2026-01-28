from datetime import timedelta
from uuid import UUID

from flask import current_app
from notifications_utils.clients.redis import (
    billable_units_sms_daily_count_cache_key,
    sms_daily_count_cache_key,
)

from app import redis_store
from app.dao.services_dao import (
    fetch_todays_total_sms_billable_units,
    fetch_todays_total_sms_count,
)


def fetch_todays_requested_sms_count(service_id: UUID) -> int:
    if not current_app.config["REDIS_ENABLED"]:
        return fetch_todays_total_sms_count(service_id)

    cache_key = sms_daily_count_cache_key(service_id)
    sms_count = redis_store.get(cache_key)
    if sms_count is None:
        sms_count = fetch_todays_total_sms_count(service_id)
        redis_store.set(cache_key, sms_count, ex=int(timedelta(hours=2).total_seconds()))
    return int(sms_count)


def increment_todays_requested_sms_count(service_id: UUID, increment_by: int):
    if not current_app.config["REDIS_ENABLED"]:
        return

    fetch_todays_requested_sms_count(service_id)  # to make sure it's set in redis
    cache_key = sms_daily_count_cache_key(service_id)
    redis_store.incrby(cache_key, increment_by)


def fetch_todays_requested_sms_billable_units_count(service_id: UUID) -> int:
    """Fetch the total SMS billable units used today for a service."""
    if not current_app.config["REDIS_ENABLED"]:
        return fetch_todays_total_sms_billable_units(service_id)

    cache_key = billable_units_sms_daily_count_cache_key(service_id)
    billable_units_count = redis_store.get(cache_key)
    if billable_units_count is None:
        billable_units_count = fetch_todays_total_sms_billable_units(service_id)
        redis_store.set(cache_key, billable_units_count, ex=int(timedelta(hours=2).total_seconds()))
    return int(billable_units_count)


def increment_todays_requested_sms_billable_units_count(service_id: UUID, increment_by: int):
    """Increment the SMS billable units count for today."""
    if not current_app.config["REDIS_ENABLED"]:
        return

    fetch_todays_requested_sms_billable_units_count(service_id)  # to make sure it's set in redis
    cache_key = billable_units_sms_daily_count_cache_key(service_id)
    redis_store.incrby(cache_key, increment_by)
