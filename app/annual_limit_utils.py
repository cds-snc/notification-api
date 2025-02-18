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


@requires_feature("REDIS_ENABLED")
def get_annual_limit_notifications_v2(service_id: UUID) -> dict:
    if not annual_limit_client.was_seeded_today(service_id):
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
    else:
        return annual_limit_client.get_all_notification_counts(service_id)
