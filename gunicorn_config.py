# flake8: noqa
import os
import sys
import time
import traceback

import cProfile
import pstats
from pstats import SortKey
from datetime import datetime

import gunicorn  # type: ignore
import newrelic.agent  # See https://bit.ly/2xBVKBH

# Check if profiling should be enabled
enable_profiling = os.getenv("NOTIFY_PROFILE") is not None
if enable_profiling:
    profiler = cProfile.Profile()

print("Initializing New Relic agent")
start_time = time.time()
newrelic.agent.initialize(environment=os.getenv("NOTIFY_ENVIRONMENT"))  # noqa: E402
end_time = time.time()
elapsed_time = end_time - start_time
print(f"Elapsed time: {elapsed_time:.2f}s")

workers = 1
worker_class = "gevent"
worker_connections = 256
bind = "0.0.0.0:{}".format(os.getenv("PORT"))
timeout = 1200  # in seconds, i.e. 20 minutes
accesslog = "-"
# Guincorn sets the server type on our app. We don't want to show it in the header in the response.
gunicorn.SERVER = "Undisclosed"

on_aws = os.environ.get("NOTIFY_ENVIRONMENT", "") in ["production", "staging", "scratch", "dev"]
if on_aws:
    # To avoid load balancers reporting errors on shutdown instances, see AWS doc
    # > We also recommend that you configure the idle timeout of your application
    # > to be larger than the idle timeout configured for the load balancer.
    # > By default, Elastic Load Balancing sets the idle timeout value for your load balancer to 60 seconds.
    # https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html#connection-idle-timeout
    keepalive = 75

    # The default graceful timeout period for Kubernetes is 30 seconds, so
    # want a lower graceful timeout value for gunicorn so that proper instance
    # shutdowns.
    #
    # Gunicorn config:
    # https://docs.gunicorn.org/en/stable/settings.html#graceful-timeout
    #
    # Kubernetes config:
    # https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/
    graceful_timeout = 25
    timeout = 30


def on_starting(server):
    server.log.info("Starting Notifications API")
    if enable_profiling:
        print("Gunicorn profiling enabled")
        global profiler
        profiler.enable()


def worker_abort(worker):
    worker.log.info("worker received ABORT {}".format(worker.pid))
    for threadId, stack in sys._current_frames().items():
        worker.log.error("".join(traceback.format_stack(stack)))


def on_exit(server):
    server.log.info("Stopping Notifications API")
    if enable_profiling:
        # Stop profiling
        global profiler
        profiler.disable()

        filestamp = datetime.now().strftime("%Y%m%d-%H%M")
        profile_by = SortKey.TIME

        # Dump profiling results to a file
        profiler.dump_stats(f"profresults/profile_results-gcrn-nr810-{profile_by}-{filestamp}.prof")
        # Analyze profiling results
        with open(f"profresults/profile_report-gcrn-nr810-{profile_by}-{filestamp}.txt", "w") as f:
            stats = pstats.Stats(f"profresults/profile_results-gcrn-nr810-{profile_by}-{filestamp}.prof", stream=f)
            stats.sort_stats(SortKey.CUMULATIVE)
            stats.print_stats()


def worker_int(worker):
    worker.log.info("worker: received SIGINT {}".format(worker.pid))
