from datetime import datetime

from flask import current_app
from notifications_utils.clients.redis import service_cache_key

from app import bounce_rate_client, notify_celery, redis_store
from app.config import QueueNames
from app.dao.service_permissions_dao import dao_remove_service_permission
from app.models import EMAIL_TYPE

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

    critical_threshold = current_app.config["BR_CRITICAL_PERCENTAGE"]
    warning_threshold = current_app.config["BR_WARNING_PERCENTAGE"]
    min_volume = current_app.config["BR_VOLUME_MINIMUM"]

    # Below volume threshold — no action
    if total_notifications < min_volume:
        return

    if bounce_rate >= critical_threshold:
        # Volume threshold met and bounce rate is critical — remove email permission
        cache_key = _bounce_rate_suspension_cache_key(service_id)
        # The RedisClient.set method calls self.redis_store.set(...) but doesn't return the result,
        # redis-py set returns True when nx=True succeeds, but the wrapper discards it and implicitly returns None.
        # Note the below method will return True ONLY the first time it is called, the next time it will return Null.
        if redis_store.redis_store.set(cache_key, datetime.utcnow().isoformat(), ex=TWENTY_FOUR_HOURS_IN_SECONDS, nx=True):
            current_app.logger.warning(
                f"Service: {service_id} has had its email permission removed due to exceeding a critical bounce rate threshold of 10%. Bounce rate: {bounce_rate} "
                f"with {total_notifications} emails sent."
            )
            if current_app.config["NOTIFY_ENVIRONMENT"] != "production":
                try:
                    deleted = dao_remove_service_permission(service_id, EMAIL_TYPE)
                    redis_store.delete(service_cache_key(service_id))
                    current_app.logger.info(f"dao_remove_service_permission returned {deleted} for service {service_id}")
                    notify_celery.send_task(
                        "send-bounce-rate-suspension-email",
                        kwargs={"service_id": str(service_id), "bounce_rate": bounce_rate},
                        queue=QueueNames.NOTIFY,
                    )
                    # Also set warning key so a warning email won't be sent if bounce rate drops to 5-10%
                    warning_cache_key = _bounce_rate_warning_cache_key(service_id)
                    redis_store.redis_store.set(
                        warning_cache_key, datetime.utcnow().isoformat(), ex=TWENTY_FOUR_HOURS_IN_SECONDS, nx=True
                    )
                except Exception:
                    current_app.logger.exception(f"Failed to suspend service {service_id}, clearing cache key to allow retry")
                    redis_store.delete(cache_key)

    elif bounce_rate >= warning_threshold:
        # Volume threshold met and bounce rate is warning — send warning email
        cache_key = _bounce_rate_warning_cache_key(service_id)
        if redis_store.redis_store.set(cache_key, datetime.utcnow().isoformat(), ex=TWENTY_FOUR_HOURS_IN_SECONDS, nx=True):
            current_app.logger.warning(
                f"Service: {service_id} has a warning bounce rate of {bounce_rate} " f"with {total_notifications} emails sent."
            )
            if current_app.config["NOTIFY_ENVIRONMENT"] != "production":
                try:
                    notify_celery.send_task(
                        "send-bounce-rate-warning-email",
                        kwargs={"service_id": str(service_id), "bounce_rate": bounce_rate},
                        queue=QueueNames.NOTIFY,
                    )
                except Exception:
                    current_app.logger.exception(
                        f"Failed to send warning email for service {service_id}, clearing cache key to allow retry"
                    )
                    redis_store.delete(cache_key)
