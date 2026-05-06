"""
scaling_api.py - Incremental load test designed to find the breaking point of the Notify API.

The test starts at a low user count and steps up every STEP_DURATION seconds, mixing
single-send POSTs, small bulk POSTs, and GET reads to simulate realistic traffic
patterns.  Bulk sends are intentionally capped at SMALL_BULK_SIZE rows so that the
API/DB layer — not CSV parsing or queue depth — is the bottleneck.

Usage (headful, for watching the dashboard):
    locust --locustfile src/scaling_api.py --headful

Usage (headless, custom ramp):
    locust --locustfile src/scaling_api.py \
           --host https://api.staging.notification.cdssandbox.xyz \
           --headless \
           --start-users 10 --step-users 20 --step-time 180 --max-users 500 \
           -r 10

Pass --max-users 0 to run indefinitely until stopped manually (Ctrl-C or web UI).

Required env vars (same as other tests in this folder, see .env.example):
    PERF_TEST_API_KEY
    PERF_TEST_EMAIL_TEMPLATE_ID_ONE_VAR
    PERF_TEST_SMS_TEMPLATE_ID_ONE_VAR
    PERF_TEST_EMAIL_ADDRESS   (optional, defaults to SES simulator address)
    PERF_TEST_PHONE_NUMBER    (optional, defaults to internal test number)
    PERF_TEST_DOMAIN          (optional, defaults to staging)
    PERF_TEST_WAF_SECRET      (optional, passed as --waf-secret; bypasses WAF rate limiting)
"""

import csv
import io
import os
import random
import threading
from collections import deque
from datetime import datetime

from dotenv import load_dotenv
from locust import HttpUser, LoadTestShape, between, events, task

# Load a .env file if one exists alongside the locustfile (no-op in production)
load_dotenv()
from locust.argument_parser import LocustArgumentParser

# ---------------------------------------------------------------------------
# Env-var helpers (no separate common module needed)
# ---------------------------------------------------------------------------


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def generate_job_rows(recipient: str, count: int) -> list[list[str]]:
    """Return *count* data rows (excluding header) for a bulk-send CSV."""
    return [[recipient, f"perf-test-{i}"] for i in range(1, count + 1)]


def rows_to_csv(rows: list[list[str]]) -> str:
    """Serialise a list of rows (including header) to a CSV string."""
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


class Config:
    API_KEY: str = _env("PERF_TEST_API_KEY")
    EMAIL_TEMPLATE_ID_ONE_VAR: str = _env("PERF_TEST_EMAIL_TEMPLATE_ID_ONE_VAR")
    SMS_TEMPLATE_ID_ONE_VAR: str = _env("PERF_TEST_SMS_TEMPLATE_ID_ONE_VAR")

    _domain: str = _env("PERF_TEST_DOMAIN", "api.staging.notification.cdssandbox.xyz")
    HOST: str = _domain if _domain.startswith("http") else f"https://{_domain}"

    EMAIL_ADDRESS: str = _env("PERF_TEST_EMAIL_ADDRESS", "success@simulator.amazonses.com")
    PHONE_NUMBER: str = _env("PERF_TEST_PHONE_NUMBER", "+16135550123")

    @classmethod
    def check(cls) -> None:
        missing = [
            name
            for name, val in (
                ("PERF_TEST_API_KEY", cls.API_KEY),
                ("PERF_TEST_EMAIL_TEMPLATE_ID_ONE_VAR", cls.EMAIL_TEMPLATE_ID_ONE_VAR),
                ("PERF_TEST_SMS_TEMPLATE_ID_ONE_VAR", cls.SMS_TEMPLATE_ID_ONE_VAR),
            )
            if not val
        ]
        if missing:
            raise EnvironmentError(f"Missing required env var(s): {', '.join(missing)}")


@events.init_command_line_parser.add_listener
def add_custom_arguments(parser: LocustArgumentParser, **kwargs):
    parser.add_argument(
        "--waf-secret",
        type=str,
        default="",
        env_var="LOCUST_WAF_SECRET",
        help="Value for the waf-secret header, used to bypass WAF rate limiting",
    )
    parser.add_argument(
        "--start-users",
        type=int,
        default=10,
        env_var="LOCUST_START_USERS",
        help="Number of concurrent users to begin with (default: 10)",
    )
    parser.add_argument(
        "--step-users",
        type=int,
        default=20,
        env_var="LOCUST_STEP_USERS",
        help="Users added at the end of each step (default: 20)",
    )
    parser.add_argument(
        "--step-time",
        type=int,
        default=180,
        env_var="LOCUST_STEP_TIME",
        help="Seconds to hold each user level before stepping up (default: 180)",
    )
    parser.add_argument(
        "--max-users",
        type=int,
        default=300,
        env_var="LOCUST_MAX_USERS",
        help="Stop the test once this user count is reached (default: 300); set to 0 for no limit",
    )


# ---------------------------------------------------------------------------
# Shared notification ID pool — POST tasks push IDs, GET tasks sample from it.
# Using a bounded deque keeps memory stable over a long run.
# ---------------------------------------------------------------------------
_notification_ids: deque = deque(maxlen=1000)
_ids_lock = threading.Lock()

# Keep bulk payloads small so the API/DB is the bottleneck, not payload size.
SMALL_BULK_SIZE = 5


def _push_id(notification_id: str) -> None:
    with _ids_lock:
        _notification_ids.append(notification_id)


def _sample_id() -> "str | None":
    """Return a random notification ID from the pool without removing it."""
    with _ids_lock:
        if not _notification_ids:
            return None
        return _notification_ids[random.randint(0, len(_notification_ids) - 1)]


# ---------------------------------------------------------------------------
# User behaviour
# Task weights must sum to 100 for easy mental math on traffic mix.
# ---------------------------------------------------------------------------


class NotifyApiUser(HttpUser):
    """Simulates a realistic mix of send (POST) and query (GET) API calls."""

    # Shorter wait than blast_api.py to push more RPS per user.
    wait_time = between(0.5, 2)
    host = Config.HOST

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        Config.check()
        self.headers = {"Authorization": f"ApiKey-v1 {Config.API_KEY}"}
        waf_secret = self.environment.parsed_options.waf_secret
        if waf_secret:
            self.headers["waf-secret"] = waf_secret

    # ------------------------------------------------------------------
    # POST tasks
    # ------------------------------------------------------------------

    @task(30)
    def send_one_email(self):
        payload = {
            "email_address": Config.EMAIL_ADDRESS,
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "personalisation": {"var": "scaling test - single email"},
        }
        with self.client.post("/v2/notifications/email", json=payload, headers=self.headers, catch_response=True) as response:
            if response.status_code == 201:
                try:
                    _push_id(response.json()["id"])
                except Exception:
                    pass

    @task(30)
    def send_one_sms(self):
        payload = {
            "phone_number": Config.PHONE_NUMBER,
            "template_id": Config.SMS_TEMPLATE_ID_ONE_VAR,
            "personalisation": {"var": "scaling test - single sms"},
        }
        with self.client.post("/v2/notifications/sms", json=payload, headers=self.headers, catch_response=True) as response:
            if response.status_code == 201:
                try:
                    _push_id(response.json()["id"])
                except Exception:
                    pass

    @task(5)
    def send_email_with_attachment(self):
        payload = {
            "email_address": Config.EMAIL_ADDRESS,
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "personalisation": {
                "var": "scaling test - attachment",
                "attached_file": {
                    "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                    "filename": "attached_file.txt",
                    "sending_method": "attach",
                },
            },
        }
        self.client.post("/v2/notifications/email", json=payload, headers=self.headers)

    @task(5)
    def send_email_with_link(self):
        payload = {
            "email_address": Config.EMAIL_ADDRESS,
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "personalisation": {
                "var": {
                    "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                    "filename": "link_file.txt",
                    "sending_method": "link",
                }
            },
        }
        self.client.post("/v2/notifications/email", json=payload, headers=self.headers)

    @task(8)
    def send_small_bulk_email(self):
        payload = {
            "name": f"Scaling bulk email {datetime.utcnow().isoformat()}",
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "csv": rows_to_csv([["email address", "var"], *generate_job_rows(Config.EMAIL_ADDRESS, SMALL_BULK_SIZE)]),
        }
        self.client.post("/v2/notifications/bulk", json=payload, headers=self.headers)

    @task(7)
    def send_small_bulk_sms(self):
        payload = {
            "name": f"Scaling bulk SMS {datetime.utcnow().isoformat()}",
            "template_id": Config.SMS_TEMPLATE_ID_ONE_VAR,
            "csv": rows_to_csv([["phone number", "var"], *generate_job_rows(Config.PHONE_NUMBER, SMALL_BULK_SIZE)]),
        }
        self.client.post("/v2/notifications/bulk", json=payload, headers=self.headers)

    # ------------------------------------------------------------------
    # GET tasks — deliberately lighter weight than the send tasks since
    # real traffic is heavily write-skewed for a notification service.
    # ------------------------------------------------------------------

    @task(10)
    def get_notification_by_id(self):
        """Retrieve a recently sent notification. Skips if the pool is still empty."""
        notification_id = _sample_id()
        if notification_id is None:
            return
        with self.client.get(
            f"/v2/notifications/{notification_id}",
            headers=self.headers,
            name="/v2/notifications/[id]",
            catch_response=True,
        ) as response:
            if response.status_code == 404:
                # Mark the original request as success so it doesn't inflate the
                # failure rate, then fire a separate stat to track 404 frequency.
                response.success()
                self.environment.events.request.fire(
                    request_type="GET",
                    name="/v2/notifications/[id] - 404",
                    response_time=response.elapsed.total_seconds() * 1000,
                    response_length=len(response.content),
                    response=response,
                    context={},
                    exception=None,
                )
            elif response.status_code >= 400:
                response.failure(f"Unexpected {response.status_code}")

    @task(5)
    def get_notification_list(self):
        """Fetch the first page of notifications — exercises the DB list query."""
        self.client.get("/v2/notifications", headers=self.headers)


# ---------------------------------------------------------------------------
# Load shape — steps up by --step-users every --step-time seconds.
#
# Example progression with defaults (step-time=180, step-users=20, start-users=10):
#   0-3 min  →  10 users
#   3-6 min  →  30 users
#   6-9 min  →  50 users
#   9-12 min →  70 users
#   …
#   ~42 min  → 300 users  (--max-users reached → test ends)
#
# All parameters are tunable at runtime via CLI flags or env vars.
# Pass --max-users 0 to run until stopped manually.
# ---------------------------------------------------------------------------


class StepwiseLoadShape(LoadTestShape):
    def tick(self):
        opts = self.runner.environment.parsed_options
        elapsed = self.get_run_time()

        step = int(elapsed // opts.step_time)
        current_users = opts.start_users + step * opts.step_users

        if opts.max_users and current_users > opts.max_users:
            return None  # Returning None tells Locust to stop the test

        # spawn_rate is the built-in Locust -r / --spawn-rate flag
        return current_users, opts.spawn_rate
