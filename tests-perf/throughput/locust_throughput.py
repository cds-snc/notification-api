"""
App-server throughput ceiling test.

Hits /_status?simple=1 — no DB call, no auth, no Redis — so the only bottleneck
is Gunicorn + gevent itself.  This lets you measure the raw request-handling
capacity of the app server before any I/O is added to the equation.

Load shape: staircase ramp.
  - Start at `--start-users` concurrent users.
  - Hold that level for `--step-time` seconds while Locust collects metrics.
  - Add `--step-users` more users and repeat forever.
  - Stop manually (Ctrl-C or the web UI) once you see saturation:
      * RPS plateaus or drops despite more users
      * p99 latency climbs sharply
      * Error rate rises

Example (headless):
    locust -f locust_throughput.py \
        --host http://localhost:6011 \
        --headless \
        --start-users 50 \
        --step-users  50 \
        --step-time   120 \
        -r 50

Example (with web UI — open http://localhost:8089):
    locust -f locust_throughput.py --host http://localhost:6011

Saturation indicators to watch in the Locust charts:
  - "Requests/s" line flattens while users keep rising  →  RPS ceiling hit
  - "50th/95th/99th percentile" response times diverge  →  queuing beginning
  - Failure count starts climbing                        →  hard limit exceeded
"""

from locust import HttpUser, LoadTestShape, constant, events, task

# ---------------------------------------------------------------------------
# CLI flags — all optional, sensible defaults work out of the box
# ---------------------------------------------------------------------------


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument(
        "--start-users",
        type=int,
        default=50,
        env_var="LOCUST_START_USERS",
        help="Number of concurrent users to begin with (default: 50)",
    )
    parser.add_argument(
        "--step-users",
        type=int,
        default=50,
        env_var="LOCUST_STEP_USERS",
        help="Users added at the end of each step (default: 50)",
    )
    parser.add_argument(
        "--step-time",
        type=int,
        default=120,
        env_var="LOCUST_STEP_TIME",
        help="Seconds to hold each user level before stepping up (default: 120)",
    )
    parser.add_argument(
        "--waf-secret",
        type=str,
        default="",
        env_var="LOCUST_WAF_SECRET",
        help="Value for the waf-secret header, used to bypass WAF rate limiting",
    )


# ---------------------------------------------------------------------------
# User behaviour — fire requests as fast as responses arrive (no wait time)
# so concurrency is driven entirely by the user count, not think-time.
# ---------------------------------------------------------------------------


class ThroughputUser(HttpUser):
    # No wait between requests: each user acts as a continuous connection,
    # immediately re-firing after a response.  This maximises load per user
    # and makes the user count a direct proxy for in-flight request concurrency.
    wait_time = constant(0)

    @task
    def ping(self):
        headers = {}
        waf_secret = self.environment.parsed_options.waf_secret
        if waf_secret:
            headers["waf-secret"] = waf_secret
        # simple=1 skips the DB version check — pure Flask routing overhead only
        self.client.get("/_status?simple=1", name="/_status?simple=1", headers=headers)


# ---------------------------------------------------------------------------
# Load shape: infinite staircase
#
#   users
#     ^
# 300 |              ___________  ...
# 200 |        _____|
# 100 |   _____|
#  50 |___|
#     +---+----+----+-----------> time (each segment = step-time seconds)
#
# tick() is called every ~1 s by Locust.  Returning None would stop the test;
# we never return None so it runs until you stop it manually.
# ---------------------------------------------------------------------------


class StepRampShape(LoadTestShape):
    def tick(self):
        opts = self.runner.environment.parsed_options
        elapsed = self.get_run_time()

        current_step = int(elapsed // opts.step_time)
        target_users = opts.start_users + (current_step * opts.step_users)

        # spawn_rate is Locust's built-in flag (-r / --spawn-rate)
        return (target_users, self.runner.environment.parsed_options.spawn_rate)
