"""
Layer 1 — API Throughput Ceiling for SMS endpoint.

Uses the simulated SMS number (+16132532222) so that notification-api
recognises the recipient and skips real Pinpoint delivery.  This isolates
API server + DB + Redis capacity from provider throughput.

Load shape: staircase ramp (same pattern as tests-perf/throughput/).
  - Start at --start-users concurrent users.
  - Hold for --step-time seconds.
  - Add --step-users more users and repeat.
  - Stop manually (Ctrl-C or web UI) when you see saturation:
      * RPS plateaus or drops
      * p99 latency climbs sharply
      * Error rate rises

Example (headless):
    locust -f locust_api_throughput.py --run-time=20m

Example (with web UI — open http://localhost:8089):
    locust -f locust_api_throughput.py
"""

import os
import random
import sys
import time

from locust import HttpUser, LoadTestShape, constant, events, task

# Allow imports from the parent directory (config, utils).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tier2_config import Config

from utils import api_headers, sms_json

Config.validate_single()


# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------
@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument(
        "--start-users", type=int, default=10, env_var="LOCUST_START_USERS", help="Concurrent users to begin with (default: 10)"
    )
    parser.add_argument(
        "--step-users", type=int, default=10, env_var="LOCUST_STEP_USERS", help="Users added at each step (default: 10)"
    )
    parser.add_argument("--step-time", type=int, default=120, env_var="LOCUST_STEP_TIME", help="Seconds per step (default: 120)")
    parser.add_argument(
        "--ref", type=str, default="tier2-L1", env_var="LOCUST_REF", help="Reference tag added to each notification"
    )


# ---------------------------------------------------------------------------
# User behaviour
# ---------------------------------------------------------------------------
class SmsThroughputUser(HttpUser):
    wait_time = constant(0)  # fire as fast as possible
    host = Config.API_HOST_NAME

    @task
    def send_sms(self):
        time.sleep(random.random() * 0.1)  # tiny jitter to avoid exact-same-instant POSTs
        ref = self.environment.parsed_options.ref
        self.client.post(
            "/v2/notifications/sms",
            json=sms_json(Config.SMS_TEMPLATE_ID, ref),
            headers=api_headers(Config.API_KEY),
        )


# ---------------------------------------------------------------------------
# Staircase load shape
# ---------------------------------------------------------------------------
class StaircaseShape(LoadTestShape):
    def tick(self):
        opts = self.runner.environment.parsed_options
        run_time = self.get_run_time()
        step = int(run_time // opts.step_time)
        user_count = opts.start_users + step * opts.step_users
        return (user_count, opts.step_users)  # (target users, spawn rate)
