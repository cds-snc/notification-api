#!/bin/sh

set -e

# Runs celery with only the delivery-receipts queue.

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --pool="${CELERY_POOL:-gevent}" --concurrency="${CELERY_CONCURRENCY-4}" -Q delivery-receipts
