#!/bin/sh

set -e

# Runs celery with only the send-sms-* queues.

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

# TODO: we shouldn't be using the send-sms-tasks queue anymore - once we verify this we can remove it
celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency="${CELERY_CONCURRENCY-4}" -Q send-sms-tasks,send-sms-high,send-sms-medium,send-sms-low
