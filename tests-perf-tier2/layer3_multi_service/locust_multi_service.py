"""
Layer 3 — Multi-Service Concurrent Load.

Each Locust user acts as a different GC Notify service, authenticated with
its own API key.  This simulates N services all sending SMS at the same time
to find the system's breaking point.

Setup:
  1.  Create N services in staging (each with an API key + SMS template).
  2.  Set PERF_TEST_API_KEYS to a comma-separated list of full API keys.
  3.  Set PERF_TEST_SMS_TEMPLATE_ID to a template that exists on *all* services
      (or set per-service template IDs if they differ — extend config.py).

Usage (staircase — recommended):
    # Start with 5 services, add 5 every 2 minutes, run for 20 min
    locust -f locust_multi_service.py \\
        --run-time=20m --start-services=5 --step-services=5 --step-time=120

Usage (fixed concurrency):
    locust -f locust_multi_service.py --run-time=10m --users=10
"""

import itertools
import os
import random
import sys
import threading
import time

from locust import HttpUser, LoadTestShape, between, events, task

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tier2_config import Config

from utils import api_headers, sms_json

Config.validate_multi()

# Build a thread-safe iterator that cycles through the API key pool.
# Each new Locust user gets the next key in round-robin order.
_key_pool = Config.api_key_pool()
_key_cycle = itertools.cycle(_key_pool)
_key_lock = threading.Lock()

print(f"[multi-service] Loaded {len(_key_pool)} API keys")


# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------
@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument(
        "--ref", type=str, default="tier2-L3", env_var="LOCUST_REF", help="Reference tag added to each notification"
    )
    parser.add_argument(
        "--start-services",
        type=int,
        default=5,
        env_var="LOCUST_START_SERVICES",
        help="Number of concurrent service-users to begin with (default: 5)",
    )
    parser.add_argument(
        "--step-services", type=int, default=5, env_var="LOCUST_STEP_SERVICES", help="Service-users added per step (default: 5)"
    )
    parser.add_argument("--step-time", type=int, default=120, env_var="LOCUST_STEP_TIME", help="Seconds per step (default: 120)")
    parser.add_argument(
        "--sms-per-second",
        type=float,
        default=1.0,
        env_var="LOCUST_SMS_PER_SECOND",
        help="Target SMS per second per service-user (default: 1.0)",
    )


# ---------------------------------------------------------------------------
# User behaviour — each user is a separate service
# ---------------------------------------------------------------------------
class ServiceUser(HttpUser):
    host = Config.API_HOST_NAME
    # Default wait_time; overridden in on_start based on --sms-per-second.
    wait_time = between(0.5, 1.5)

    def on_start(self):
        with _key_lock:
            self.api_key = next(_key_cycle)
        self.headers = api_headers(self.api_key)
        # Derive a short service tag from the key for tracing.
        self.service_tag = self.api_key[-8:]

    @task
    def send_sms(self):
        time.sleep(random.random() * 0.2)  # jitter
        ref = f"{self.environment.parsed_options.ref}-{self.service_tag}"
        response = self.client.post(
            "/v2/notifications/sms",
            json=sms_json(Config.SMS_TEMPLATE_ID, ref),
            headers=self.headers,
            catch_response=True,
        )
        with response as resp:
            if resp.status_code == 201:
                resp.success()
            elif resp.status_code == 429:
                # Daily limit hit for this service — expected.
                resp.success()
            else:
                resp.failure(f"[{self.service_tag}] status {resp.status_code}")


# ---------------------------------------------------------------------------
# Staircase load shape (optional — only used if --start-services is set)
# ---------------------------------------------------------------------------
class MultiServiceStaircase(LoadTestShape):
    def tick(self):
        opts = self.runner.environment.parsed_options
        run_time = self.get_run_time()
        step = int(run_time // opts.step_time)
        target = min(
            opts.start_services + step * opts.step_services,
            len(_key_pool),  # can't have more users than API keys
        )
        return (target, opts.step_services)
