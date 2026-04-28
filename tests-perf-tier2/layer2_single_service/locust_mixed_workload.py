"""
Layer 2c — Mixed Workload: 1,500 SMS + 10,000 emails concurrently.

Verifies that SMS and email daily limits are enforced independently
and that mixed traffic doesn't cause unexpected interference.

Usage:
    locust -f locust_mixed_workload.py --run-time=30m --users=10
"""

import os
import random
import sys
import time

from locust import HttpUser, between, events, task

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tier2_config import Config

from utils import api_headers, email_json, sms_json

Config.validate_single()
if not Config.EMAIL_TEMPLATE_ID:
    raise ValueError("PERF_TEST_EMAIL_TEMPLATE_ID is required for the mixed workload test")


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument(
        "--ref", type=str, default="tier2-L2-mixed", env_var="LOCUST_REF", help="Reference tag added to each notification"
    )


class MixedWorkloadUser(HttpUser):
    """
    Weighted tasks: emails are ~6.7x more frequent than SMS
    (10,000 emails : 1,500 SMS ≈ 87:13 ratio).
    """

    wait_time = between(0.05, 0.2)
    host = Config.API_HOST_NAME

    @task(13)
    def send_sms(self):
        time.sleep(random.random() * 0.1)
        ref = self.environment.parsed_options.ref
        response = self.client.post(
            "/v2/notifications/sms",
            json=sms_json(Config.SMS_TEMPLATE_ID, ref),
            headers=api_headers(Config.API_KEY),
            catch_response=True,
        )
        with response as resp:
            if resp.status_code in (201, 429):
                resp.success()
            else:
                resp.failure(f"SMS unexpected {resp.status_code}")

    @task(87)
    def send_email(self):
        time.sleep(random.random() * 0.1)
        ref = self.environment.parsed_options.ref
        response = self.client.post(
            "/v2/notifications/email",
            json=email_json(Config.EMAIL_TEMPLATE_ID, ref),
            headers=api_headers(Config.API_KEY),
            catch_response=True,
        )
        with response as resp:
            if resp.status_code in (201, 429):
                resp.success()
            else:
                resp.failure(f"Email unexpected {resp.status_code}")
