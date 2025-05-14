from datetime import datetime, timezone
from typing import Tuple
from uuid import UUID

from flask import current_app
from notifications_utils.clients.redis.annual_limit import (
    TOTAL_EMAIL_FISCAL_YEAR_TO_YESTERDAY,
    TOTAL_SMS_FISCAL_YEAR_TO_YESTERDAY,
    annual_limit_notifications_v2_key,
)
from notifications_utils.decorators import requires_feature

from app import annual_limit_client
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_for_service_for_day,
    fetch_notification_status_totals_for_service_by_fiscal_year,
)
from app.models import EMAIL_TYPE, SMS_TYPE
from app.utils import get_fiscal_year, prepare_notification_counts_for_seeding


def seed_data_in_redis(service_id: UUID) -> dict:
    """
    Seed the annual limit notification counts for a service in redis.
    """
    today = datetime.now(timezone.utc)
    annual_data_sms = fetch_notification_status_totals_for_service_by_fiscal_year(
        service_id, get_fiscal_year(today), notification_type=SMS_TYPE
    )
    annual_data_email = fetch_notification_status_totals_for_service_by_fiscal_year(
        service_id, get_fiscal_year(today), notification_type=EMAIL_TYPE
    )
    data = prepare_notification_counts_for_seeding(
        fetch_notification_status_for_service_for_day(
            datetime.now(timezone.utc),
            service_id=service_id,
        )
    )
    data[TOTAL_SMS_FISCAL_YEAR_TO_YESTERDAY] = annual_data_sms
    data[TOTAL_EMAIL_FISCAL_YEAR_TO_YESTERDAY] = annual_data_email

    # The below function will also set the SEEDED_AT key for notifications_v2 in redis
    annual_limit_client.seed_annual_limit_notifications(service_id, data)
    return data


@requires_feature("REDIS_ENABLED")
def get_annual_limit_notifications_v2(service_id: UUID) -> dict:
    if not annual_limit_client.was_seeded_today(service_id):
        data = seed_data_in_redis(service_id)
        return data
    else:
        annual_data = annual_limit_client.get_all_notification_counts(service_id)
        if TOTAL_EMAIL_FISCAL_YEAR_TO_YESTERDAY in annual_data:
            return annual_data
        else:
            data = seed_data_in_redis(service_id)
            current_app.logger.info(
                f"Service {service_id} missing seed data. "
                f"Original Data in redis: {annual_data}. "
                f"New Data in redis: {data}."
            )
            return data


@requires_feature("REDIS_ENABLED")
def get_annual_limit_notifications_v3(service_id: UUID) -> Tuple[dict, bool]:
    if not annual_limit_client.was_seeded_today(service_id):
        current_app.logger.info(f"[alimit-debug] Service {service_id} was not seeded.")
        data = seed_data_in_redis(service_id)
        return (data, True)
    else:
        annual_data = annual_limit_client.get_all_notification_counts(service_id)
        email_fiscal = annual_limit_client._redis_client.get_hash_field(
            annual_limit_notifications_v2_key(service_id), TOTAL_EMAIL_FISCAL_YEAR_TO_YESTERDAY
        )
        sms_fiscal = annual_limit_client._redis_client.get_hash_field(
            annual_limit_notifications_v2_key(service_id), TOTAL_SMS_FISCAL_YEAR_TO_YESTERDAY
        )

        current_app.logger.info(f"[alimit-debug] service_id: {service_id} email_fiscal: {email_fiscal}")
        if email_fiscal is not None or sms_fiscal is not None:
            current_app.logger.info(f"[alimit-debug] service {service_id} was seeded. annual_data: {annual_data}")
            return (annual_data, False)
        else:
            data = seed_data_in_redis(service_id)
            current_app.logger.info(
                f"[alimit-debug] Service {service_id} missing seed data. "
                f"Original Data in redis: {annual_data}. "
                f"New Data in redis: {data}."
            )
            return (data, True)
