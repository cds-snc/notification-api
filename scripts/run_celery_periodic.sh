#!/bin/sh

set -e

# Runs celery with periodic-tasks and job-tasks queues.

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --pool="${CELERY_POOL:-prefork}" --concurrency="${CELERY_CONCURRENCY-4}" -Q periodic-tasks,job-tasks
