"""
Layer 2b — SMS Burst Test.

Sends 1,500 SMS as fast as possible from a single service using multiple
concurrent Locust users.  Measures API acceptance rate and end-to-end
delivery time.

Usage:
    # 25 concurrent users, each ~60 SMS = 1,500 total
    locust -f locust_burst_sms.py --run-time=10m --users=25

    # More aggressive: 50 users, faster burst
    locust -f locust_burst_sms.py --run-time=5m --users=50
"""

import os
import random
import sys
import threading
import time

from locust import HttpUser, constant, events, task

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tier2_config import Config

from utils import api_headers, sms_json

Config.validate_single()

# Shared counter — tracks total sends across all users.
_lock = threading.Lock()
_total_sent = 0
_total_rejected = 0


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument(
        "--ref", type=str, default="tier2-L2-burst", env_var="LOCUST_REF", help="Reference tag added to each notification"
    )


class BurstSmsUser(HttpUser):
    wait_time = constant(0)  # as fast as possible
    host = Config.API_HOST_NAME

    @task
    def send_sms(self):
        global _total_sent, _total_rejected

        with _lock:
            if _total_sent >= Config.SMS_DAILY_LIMIT:
                # Already hit the limit — stop sending.
                if _total_rejected == 0:
                    print(f"[burst] All {_total_sent} SMS sent. Waiting for stragglers...")
                _total_rejected += 1
                if _total_rejected >= 50:
                    self.environment.runner.quit()
                return

        time.sleep(random.random() * 0.05)  # tiny jitter
        ref = self.environment.parsed_options.ref
        response = self.client.post(
            "/v2/notifications/sms",
            json=sms_json(Config.SMS_TEMPLATE_ID, ref),
            headers=api_headers(Config.API_KEY),
            catch_response=True,
        )
        with response as resp:
            if resp.status_code == 201:
                with _lock:
                    _total_sent += 1
                    count = _total_sent
                resp.success()
                if count % 250 == 0:
                    print(f"[burst] {count}/{Config.SMS_DAILY_LIMIT} sent")
            elif resp.status_code == 429:
                resp.success()  # expected at limit
                with _lock:
                    _total_rejected += 1
            else:
                resp.failure(f"Unexpected status {resp.status_code}")
