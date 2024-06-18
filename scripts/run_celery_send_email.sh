#!/bin/sh

set -e

# Runs celery with only the send-email-* queues.

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency="${CELERY_CONCURRENCY-4}" -Q send-email-high,send-email-medium,send-email-low
