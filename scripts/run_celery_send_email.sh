#!/bin/sh

# runs celery with only the send-email-* queues

set -e

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

# TODO: we shouldn't be using the send-email-tasks queue anymore - once we verify this we can remove it
celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency=${CELERY_CONCURRENCY-4} -Q send-email-tasks,send-email-high,send-email-medium,send-email-low
