#!/bin/sh

set -e

# Necessary to run as exec so the PID is transferred to Celery for the `SIGTERM` sent from ECS
exec celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency=4
