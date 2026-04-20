#!/bin/sh

set -e

# Placeholder: Runs celery with only the SMS fair queue.
# Real fair-queue implementation to follow.

echo "Start celery fair SMS worker (PLACEHOLDER), concurrency: ${CELERY_CONCURRENCY-4}"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency=1 -Q send-sms-fair