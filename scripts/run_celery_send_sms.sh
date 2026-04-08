#!/bin/sh

set -e

# Runs celery with only SMS lane queues.
# The control-lane queue is the single SMS fair queue used when FF_SMS_CONTROL_LANE is enabled.

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency="${CELERY_CONCURRENCY-4}" -Q send-sms-fair,send-sms-high,send-sms-medium,send-sms-low,send-throttled-sms-tasks
