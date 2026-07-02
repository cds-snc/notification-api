#!/bin/sh

set -e

# Runs celery with only the throttled sms sending queue.

celery -A run_celery.notify_celery worker --loglevel=INFO --pool="${CELERY_POOL:-prefork}" --concurrency=1 -Q send-throttled-sms-tasks
