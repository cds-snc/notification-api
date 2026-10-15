#!/bin/sh

set -e

echo "Start dedicated celery worker for process-jobs, concurrency: 1"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --pool="${CELERY_POOL:-prefork}" --concurrency=1 -Q process-jobs
