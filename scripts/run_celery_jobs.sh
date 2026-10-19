#!/bin/sh

set -e

echo "Start dedicated celery worker for job-tasks, concurrency: ${CELERY_CONCURRENCY-4}"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --pool="${CELERY_POOL:-prefork}" --concurrency="${CELERY_CONCURRENCY-4}" -Q job-tasks
