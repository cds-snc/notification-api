#!/bin/sh

set -e

# Runs a dedicated Celery worker for long-running nightly tasks (notification
# deletes, inbound SMS cleanup, etc.).
#
# This worker is intentionally isolated from the main periodic-tasks worker so
# that its Kubernetes deployment can carry a high terminationGracePeriodSeconds
# (e.g. 2100s / 35 min) without forcing the same slow shutdown on workers that
# handle short-lived per-minute tasks.
#
# The corresponding K8s deployment should set:
#   terminationGracePeriodSeconds: 2100

echo "Start nightly celery worker, concurrency: 1"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --pool="${CELERY_POOL:-prefork}" --concurrency=1 -Q nightly-tasks
