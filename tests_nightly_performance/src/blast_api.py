"""
blast_api.py - Open-ended stress test that continuously ramps up users to find the
breaking point of the Notify API with no upper ceiling.

Sends a realistic mix of single email/SMS POSTs, emails with attachments/links, and
bulk sends. Optionally includes GET-by-ID and GET-list tasks (off by default).

Usage (headful, for watching the dashboard):
    locust --locustfile src/blast_api.py --headful

Usage (headless, via execute_and_publish_performance_test.sh):
    locust --config locust.conf \
           --locustfile src/blast_api.py \
           --users 3000 \
           --bulk-size 2

Key CLI flags:
    --skip-bulk           Skip bulk send tasks
    --bulk-only           Only run bulk send tasks
    --bulk-size INT        Recipients per bulk send (default: 2000)
    --start-users INT      Immediately ramp to this many users, then step up by 50 every 120s
    --constant-users INT   Hold a fixed user count indefinitely (no step-up)
    --include-get          Also run GET notification tasks
    --get-only             Only run GET tasks (implies --include-get)
    --pacing FLOAT         Seconds between tasks per user, constant_pacing (default: 60)
    --wait-min FLOAT       Switch to between() mode; sets minimum wait seconds
    --wait-max FLOAT       Maximum wait seconds for between() mode (default: same as --wait-min)

Required env vars:
    PERF_TEST_API_KEY
    PERF_TEST_EMAIL_TEMPLATE_ID_ONE_VAR
    PERF_TEST_SMS_TEMPLATE_ID_ONE_VAR
    PERF_TEST_EMAIL_ADDRESS   (optional, defaults to SES simulator address)
    PERF_TEST_PHONE_NUMBER    (optional, defaults to internal test number)
    PERF_TEST_DOMAIN          (optional, defaults to staging)
    PERF_TEST_WAF_SECRET      (optional, bypasses WAF rate limiting)
"""

import random
from collections import deque
from datetime import datetime

import gevent
from dotenv import load_dotenv
from locust import HttpUser, LoadTestShape, between, constant_pacing, events, task

from common import Config, generate_job_rows, rows_to_csv

load_dotenv()

_max_rps: float = 0.0
_max_users: int = 0
_rps_at_first_error: float | None = None
_prev_error_count: int = 0
_rps_sampler_greenlet = None


def _sample_rps(environment):
    global _max_rps, _max_users, _rps_at_first_error, _prev_error_count
    while True:
        runner = environment.runner
        if runner:
            rps = runner.stats.total.current_rps
            if rps > _max_rps:
                _max_rps = rps
            user_count = runner.user_count
            if user_count > _max_users:
                _max_users = user_count
            error_count = runner.stats.total.num_failures
            if _rps_at_first_error is None and error_count > _prev_error_count:
                _rps_at_first_error = rps
            _prev_error_count = error_count
        gevent.sleep(1)


@events.init.add_listener
def on_init(environment, **kwargs):
    global _rps_sampler_greenlet
    _rps_sampler_greenlet = gevent.spawn(_sample_rps, environment)


@events.quitting.add_listener
def print_max_rps(environment, **kwargs):
    if _rps_sampler_greenlet:
        _rps_sampler_greenlet.kill()
    print(f"\n*** Maximum send rate observed: {_max_rps:.2f} req/s ***")
    print(f"*** Maximum concurrent users: {_max_users} ***")
    if _rps_at_first_error is not None:
        print(f"*** Send rate when errors first appeared: {_rps_at_first_error:.2f} req/s ***")
    else:
        print("*** No errors observed during test ***")
    print()


@events.init_command_line_parser.add_listener
def add_custom_arguments(parser, **kwargs):
    parser.add_argument("--skip-bulk", action="store_true", default=False, help="Skip bulk send tasks")
    parser.add_argument("--bulk-only", action="store_true", default=False, help="Only run bulk send tasks, skip individual sends")
    parser.add_argument("--bulk-size", type=int, default=BULK_SIZE, help=f"Number of messages per bulk send request (default: {BULK_SIZE})")
    parser.add_argument("--start-users", type=int, default=0, help="Number of users to start with before stepping up")
    parser.add_argument("--constant-users", type=int, default=0, help="Maintain a fixed number of users indefinitely with no step-up")
    parser.add_argument("--include-get", action="store_true", default=False, help="Include GET notification requests in the test (by ID and list)")
    parser.add_argument("--get-only", action="store_true", default=False, help="Only run GET notification tasks, skip all send tasks (implies --include-get)")
    parser.add_argument("--pacing", type=float, default=60.0, help="Seconds between tasks per user using constant_pacing (default: 60). Ignored if --wait-min/--wait-max are set.")
    parser.add_argument("--wait-min", type=float, default=None, help="Minimum wait seconds between tasks (enables between() mode instead of constant_pacing)")
    parser.add_argument("--wait-max", type=float, default=None, help="Maximum wait seconds between tasks (used with --wait-min)")

BULK_SIZE = 2000

# Note that task weights add up to 100
# If you add / remove tasks please keep the sum 100


class NotifyApiUser(HttpUser):
    host = Config.HOST

    def wait_time(self):
        opts = self.environment.parsed_options
        if opts.wait_min is not None:
            wait_max = opts.wait_max if opts.wait_max is not None else opts.wait_min
            return between(opts.wait_min, wait_max)(self)
        return constant_pacing(opts.pacing)(self)

    _sent_ids: deque = deque(maxlen=500)  # shared pool of sent notification IDs for GET tasks

    def __init__(self, *args, **kwargs):
        super(NotifyApiUser, self).__init__(*args, **kwargs)
        Config.check()
        self.headers = {"Authorization": f"ApiKey-v1 {Config.API_KEY}"}
        if Config.WAF_SECRET:
            self.headers["waf-secret"] = Config.WAF_SECRET

    @task(30)
    def send_one_email(self):
        if self.environment.parsed_options.bulk_only or self.environment.parsed_options.get_only:
            return
        json = {
            "email_address": Config.EMAIL_ADDRESS,
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "personalisation": {"var": "single email"},
        }
        response = self.client.post("/v2/notifications/email", json=json, headers=self.headers)
        if response.status_code == 201:
            try:
                NotifyApiUser._sent_ids.append(response.json()["id"])
            except Exception:
                pass

    @task(30)
    def send_one_sms(self):
        if self.environment.parsed_options.bulk_only or self.environment.parsed_options.get_only:
            return
        json = {
            "phone_number": Config.PHONE_NUMBER,
            "template_id": Config.SMS_TEMPLATE_ID_ONE_VAR,
            "personalisation": {"var": "single sms"},
        }
        response = self.client.post("/v2/notifications/sms", json=json, headers=self.headers)
        if response.status_code == 201:
            try:
                NotifyApiUser._sent_ids.append(response.json()["id"])
            except Exception:
                pass

    @task(5)
    def send_email_with_attachment(self):
        if self.environment.parsed_options.bulk_only or self.environment.parsed_options.get_only:
            return
        json = {
            "email_address": Config.EMAIL_ADDRESS,
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "personalisation": {
                "var": "email with attachment",
                "attached_file": {
                    "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                    "filename": "attached_file.txt",
                    "sending_method": "attach",
                },
            },
        }
        self.client.post("/v2/notifications/email", json=json, headers=self.headers)

    @task(5)
    def send_email_with_link_notifications(self):
        if self.environment.parsed_options.bulk_only or self.environment.parsed_options.get_only:
            return
        json = {
            "email_address": Config.EMAIL_ADDRESS,
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "personalisation": {
                "var": {
                    "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                    "filename": "attached_file.txt",
                    "sending_method": "link",
                }
            },
        }
        self.client.post("/v2/notifications/email", json=json, headers=self.headers)

    @task(10)
    def get_notification_by_id(self):
        opts = self.environment.parsed_options
        if not opts.include_get and not opts.get_only:
            return
        if not NotifyApiUser._sent_ids:
            return
        notification_id = random.choice(list(NotifyApiUser._sent_ids))
        self.client.get(f"/v2/notifications/{notification_id}", headers=self.headers)

    @task(10)
    def get_notifications_list(self):
        opts = self.environment.parsed_options
        if not opts.include_get and not opts.get_only:
            return
        self.client.get("/v2/notifications", headers=self.headers)

    @task(20)
    def send_bulk_emails(self):
        if self.environment.parsed_options.skip_bulk or self.environment.parsed_options.get_only:
            return
        bulk_size = self.environment.parsed_options.bulk_size
        json = {
            "name": f"Email send rate test {datetime.utcnow().isoformat()}",
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "csv": rows_to_csv([["email address", "var"], *generate_job_rows(Config.EMAIL_ADDRESS, bulk_size)]),
        }
        self.client.post("/v2/notifications/bulk", json=json, headers=self.headers)


class StepLoadShape(LoadTestShape):
    """Controls user ramp-up behaviour.

    Default (no flags): holds --users at the spawn-rate set in locust.conf, matching
    the nightly runner behaviour exactly (flat load, no step-up).

    With --constant-users N: ramps to N users immediately and holds indefinitely.

    With --start-users N: shocks to N users on start, then steps up by STEP_USERS
    every STEP_DURATION seconds indefinitely.
    """

    STEP_USERS = 50  # users to add per step (only used with --start-users)
    STEP_DURATION = 120  # seconds per step

    def tick(self):
        run_time = self.get_run_time()
        opts = self.runner.environment.parsed_options
        constant_users = opts.constant_users
        start_users = opts.start_users
        spawn_rate = opts.spawn_rate  # honours -r / locust.conf spawn-rate
        current_step = int(run_time / self.STEP_DURATION)

        if constant_users > 0:
            # Hold a fixed number of users indefinitely, no step-up
            return (constant_users, constant_users if run_time < 1 else spawn_rate)

        if start_users > 0:
            # Shock the system immediately with all start_users, then step up from there
            if current_step == 0:
                return (start_users, start_users)
            target_users = start_users + current_step * self.STEP_USERS
            return (target_users, spawn_rate)

        # Default: flat load using --users and --spawn-rate from CLI / locust.conf
        return (opts.num_users, spawn_rate)
