#!/bin/sh

# runs celery with all celery queues
# This is for local use only, NOT for use in AWS

set -e

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency="${CELERY_CONCURRENCY-4}" -Q database-tasks,-priority-database-tasks.fifo,-normal-database-tasks,-bulk-database-tasks,job-tasks,notify-internal-tasks,periodic-tasks,priority-tasks,normal-tasks,bulk-tasks,reporting-tasks,research-mode-tasks,retry-tasks,send-sms-tasks,send-sms-high,send-sms-medium,send-sms-low,send-throttled-sms-tasks,send-email-high,send-email-medium,send-email-low,send-email-tasks,service-callbacks,delivery-receipts
