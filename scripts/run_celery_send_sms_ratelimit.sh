#!/bin/sh

set -e

# Placeholder: single-worker SMS control lane for rate-limited flow.
# Real fair-queue implementation and tuning to follow.

echo "Start celery SMS rate-limit worker (PLACEHOLDER), concurrency: 1"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency="${CELERY_CONCURRENCY-4}" -Q send-sms-fair
