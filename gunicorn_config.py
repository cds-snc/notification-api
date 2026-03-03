import os
import sys
import time
import traceback

import gunicorn  # type: ignore
from environs import Env

environment = os.environ.get("NOTIFY_ENVIRONMENT")

# Ensure these are always defined so other code can rely on them.
os.environ.setdefault("FF_ENABLE_OTEL", os.getenv("FF_ENABLE_OTEL", "False"))
os.environ.setdefault("ENABLE_NEW_RELIC", os.getenv("ENABLE_NEW_RELIC", "False"))
os.environ.setdefault("NEW_RELIC_CONFIG_FILE", os.getenv("NEW_RELIC_CONFIG_FILE", "newrelic.ini"))

env = Env()

ff_enable_otel = env.bool("FF_ENABLE_OTEL", default=False)
enable_newrelic = env.bool("ENABLE_NEW_RELIC", default=False) and not ff_enable_otel

print("enable_newrelic =", enable_newrelic)

if enable_newrelic:
    import newrelic.agent

    newrelic.agent.initialize(environment=environment)  # noqa: E402

default_worker_class = "gevent_otel_worker.OTelAwareGeventWorker" if ff_enable_otel else "gevent"

workers = int(os.getenv("GUNICORN_WORKERS", "4"))
worker_class = os.getenv("GUNICORN_WORKER_CLASS", default_worker_class)
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "256"))
preload_app = env.bool("GUNICORN_PRELOAD_APP", default=False)
bind = "0.0.0.0:{}".format(os.getenv("PORT"))
accesslog = "-"
access_log_format = '%(h)s %(l)s %(u)s [%(t)s] "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" request_time_us=%(D)s request_time_s=%(T)s'
# Guincorn sets the server type on our app. We don't want to show it in the header in the response.
gunicorn.SERVER = "Undisclosed"

on_aws = environment in [
    "production",
    "staging",
    "scratch",
    "dev",
]
if on_aws:
    # To avoid load balancers reporting errors on shutdown instances, see AWS doc
    # > We also recommend that you configure the idle timeout of your application
    # > to be larger than the idle timeout configured for the load balancer.
    # > By default, Elastic Load Balancing sets the idle timeout value for your load balancer to 60 seconds.
    # https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html#connection-idle-timeout
    keepalive = 75

    # The default graceful timeout period for Kubernetes is 30 seconds, so
    # make sure that the timeouts defined here are less than the configured
    # Kubernetes timeout. This ensures that the gunicorn worker will exit
    # before the Kubernetes pod is terminated. This is important because
    # Kubernetes will send a SIGKILL to the pod if it does not terminate
    # within the grace period. If the worker is still processing requests
    # when it receives the SIGKILL, it will be terminated abruptly and
    # will not be able to finish processing the request. This can lead to
    # 502 errors being returned to the client.
    #
    # Also, some libraries such as NewRelic might need some time to finish
    # initialization before the worker can start processing requests. The
    # timeout values should consider these factors.
    #
    # Gunicorn config:
    # https://docs.gunicorn.org/en/stable/settings.html#graceful-timeout
    #
    # Kubernetes config:
    # https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/
    graceful_timeout = 85
    timeout = 90

# Start timer for total running time
start_time = time.time()


def on_starting(server):
    server.log.info("Starting Notifications API")


def worker_abort(worker):
    worker.log.info("worker received ABORT {}".format(worker.pid))
    for threadId, stack in sys._current_frames().items():
        worker.log.error("".join(traceback.format_stack(stack)))


def on_exit(server):
    elapsed_time = time.time() - start_time
    server.log.info("Stopping Notifications API")
    server.log.info("Total gunicorn API running time: {:.2f} seconds".format(elapsed_time))


def worker_int(worker):
    worker.log.info("worker: received SIGINT {}".format(worker.pid))
