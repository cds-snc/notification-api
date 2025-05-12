from datetime import datetime, timezone
from uuid import UUID

from notifications_utils.clients.redis.annual_limit import (
    TOTAL_EMAIL_FISCAL_YEAR_TO_YESTERDAY,
    TOTAL_SMS_FISCAL_YEAR_TO_YESTERDAY,
)
from notifications_utils.decorators import requires_feature

from app import annual_limit_client
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_for_service_for_day,
    fetch_notification_status_totals_for_service_by_fiscal_year,
)
from app.models import EMAIL_TYPE, SMS_TYPE
from app.utils import get_fiscal_year, prepare_notification_counts_for_seeding


def seed_annual_limit_counts(service_id: UUID) -> dict:
    """
    Seed the annual limit counts for a service. This is called when the service is created or updated.
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
        return seed_annual_limit_counts(service_id)
    else:
        return annual_limit_client.get_all_notification_counts(service_id)


@requires_feature("REDIS_ENABLED")
def increment_notifications_failed(service_id: UUID, notification_type) -> None:
    if not annual_limit_client.was_seeded_today(service_id):
        seed_annual_limit_counts(service_id)
    else:
        if notification_type == EMAIL_TYPE:
            annual_limit_client.increment_email_failed(service_id)
        elif notification_type == SMS_TYPE:
            annual_limit_client.increment_sms_failed(service_id)


@requires_feature("REDIS_ENABLED")
def increment_notifications_delivered(service_id: UUID, notification_type) -> None:
    if not annual_limit_client.was_seeded_today(service_id):
        seed_annual_limit_counts(service_id)
    else:
        if notification_type == EMAIL_TYPE:
            annual_limit_client.increment_email_delivered(service_id)
        elif notification_type == SMS_TYPE:
            annual_limit_client.increment_sms_delivered(service_id)
