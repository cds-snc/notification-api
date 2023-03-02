import time

from flask import current_app
from notifications_utils.clients.redis import (
    add_key_to_sorted_set,
    get_length_of_sorted_set,
)
from redis import Redis


def _hard_bounce_total_key(service_id):
    return f"hard_bounce_total:{service_id}"


def _total_notifications_key(service_id):
    return f"total_notifications:{service_id}"


def _twenty_four_hour_window():
    return 60 * 60 * 24


def _current_time():
    return int(time.time())


class RedisBounceRate:
    def init_app(self, redis: Redis):
        self._redis_client = redis

    def set_hard_bounce(self, service_id):
        add_key_to_sorted_set(self._redis_client, self.hard_bounce_total_key(service_id), _current_time())

    def set_total_notifications(self, service_id):
        add_key_to_sorted_set(self._redis_client, self.total_notifications_key(service_id), _current_time())

    def get_bounce_rate(self, service_id):
        current_app.logger.info(f"Getting bounce rate for {service_id}")
        total_hard_bounces = get_length_of_sorted_set(
            self._redis_client, self.hard_bounce_total_key(service_id), _twenty_four_hour_window()
        )
        total_notifications = get_length_of_sorted_set(
            self._redis_client, self.total_notifications_key(service_id), _twenty_four_hour_window()
        )
        return round(total_hard_bounces / total_notifications, 2) if total_notifications else 0
