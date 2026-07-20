from datetime import datetime

from flask import current_app

from app import bounce_rate_client, notify_celery, redis_store
from app.config import QueueNames
from app.dao.services_dao import dao_suspend_service
from app.models import BounceRateStatus

TWENTY_FOUR_HOURS_IN_SECONDS = 24 * 60 * 60


def _bounce_rate_suspension_cache_key(service_id: str) -> str:
    return f"bounce-rate-suspension-email-sent:{service_id}"


def _bounce_rate_warning_cache_key(service_id: str) -> str:
    return f"bounce-rate-warning-email-sent:{service_id}"


def check_service_over_bounce_rate(service_id: str):
    bounce_rate = bounce_rate_client.get_bounce_rate(service_id)
    bounce_rate_status = bounce_rate_client.check_bounce_rate_status(service_id)
    total_notifications = bounce_rate_client.get_total_notifications(service_id)
    current_app.logger.info(
        f"Service id: {service_id} Bounce Rate: {bounce_rate} Bounce Status: {bounce_rate_status}, "
        f"Total Notifications: {total_notifications}"
    )

    if bounce_rate_status == BounceRateStatus.CRITICAL.value:
        min_volume = current_app.config["BR_VOLUME_MINIMUM"]

        if total_notifications >= min_volume:
            # Volume threshold met and bounce rate is critical — suspend the service
            cache_key = _bounce_rate_suspension_cache_key(service_id)
            if not redis_store.get(cache_key):
                current_app.logger.warning(
                    f"Service: {service_id} has been suspended. Bounce rate {bounce_rate} exceeds critical threshold "
                    f"with {total_notifications} emails sent (>= {min_volume})."
                )
                if current_app.config["NOTIFY_ENVIRONMENT"] != "production":
                    dao_suspend_service(service_id)
                    notify_celery.send_task(
                        "send-bounce-rate-suspension-email",
                        kwargs={"service_id": str(service_id), "bounce_rate": bounce_rate},
                        queue=QueueNames.NOTIFY,
                    )
                redis_store.set(cache_key, datetime.utcnow().isoformat(), ex=TWENTY_FOUR_HOURS_IN_SECONDS)
        else:
            # Volume threshold NOT met — warn only
            cache_key = _bounce_rate_warning_cache_key(service_id)
            if not redis_store.get(cache_key):
                current_app.logger.warning(
                    f"Service: {service_id} has a critical bounce rate of {bounce_rate} but has only sent "
                    f"{total_notifications} emails (< {min_volume}). Sending warning email."
                )
                if current_app.config["NOTIFY_ENVIRONMENT"] != "production":
                    notify_celery.send_task(
                        "send-bounce-rate-warning-email",
                        kwargs={"service_id": str(service_id), "bounce_rate": bounce_rate},
                        queue=QueueNames.NOTIFY,
                    )
                    redis_store.set(cache_key, datetime.utcnow().isoformat(), ex=TWENTY_FOUR_HOURS_IN_SECONDS)

    elif bounce_rate_status == BounceRateStatus.WARNING.value:
        current_app.logger.warning(
            f"Service: {service_id} has met or exceeded a warning bounce rate threshold of 5%. Bounce rate: {bounce_rate}"
        )
