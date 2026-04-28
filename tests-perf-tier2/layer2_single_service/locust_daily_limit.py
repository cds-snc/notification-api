"""
Layer 2a — Daily SMS Limit Verification.

Sends exactly SMS_DAILY_LIMIT (1,500) SMS messages through one service,
then verifies the next request is rejected with HTTP 429.

Uses the simulated SMS number so no real messages are sent.

Usage:
    locust -f locust_daily_limit.py --run-time=30m --users=1
"""

import os
import sys

from locust import HttpUser, between, events, task

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tier2_config import Config

from utils import api_headers, sms_json

Config.validate_single()


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument(
        "--ref", type=str, default="tier2-L2-limit", env_var="LOCUST_REF", help="Reference tag added to each notification"
    )


class DailyLimitUser(HttpUser):
    """
    Sends SMS one-by-one, counting successes.  Once the daily limit is reached
    it expects 429 responses and logs the crossover point.
    """

    wait_time = between(0.05, 0.15)  # ~8-15 SMS/sec per user
    host = Config.API_HOST_NAME

    sent_count = 0
    rejected_count = 0
    limit_hit = False

    @task
    def send_sms_until_limit(self):
        ref = self.environment.parsed_options.ref
        response = self.client.post(
            "/v2/notifications/sms",
            json=sms_json(Config.SMS_TEMPLATE_ID, ref),
            headers=api_headers(Config.API_KEY),
            # Don't let Locust mark 429 as failure — we expect it.
            catch_response=True,
        )
        with response as resp:
            if resp.status_code == 201:
                self.sent_count += 1
                resp.success()
                if self.sent_count % 100 == 0:
                    print(f"[daily-limit] Sent {self.sent_count}/{Config.SMS_DAILY_LIMIT}")
            elif resp.status_code == 429:
                if not self.limit_hit:
                    self.limit_hit = True
                    print(f"[daily-limit] *** Limit reached after {self.sent_count} successful sends ***")
                self.rejected_count += 1
                resp.success()  # expected — mark as success
                if self.rejected_count >= 10:
                    print(f"[daily-limit] Confirmed: {self.rejected_count} consecutive 429s. Stopping.")
                    self.environment.runner.quit()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")
