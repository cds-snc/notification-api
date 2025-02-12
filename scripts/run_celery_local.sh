#!/bin/sh

# runs celery with all celery queues
# This is for local use only, NOT for use in AWS

set -e

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

celery -A run_celery.notify_celery worker --beat --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency="${CELERY_CONCURRENCY-4}" -Q -priority-database-tasks.fifo,-normal-database-tasks,-bulk-database-tasks,job-tasks,notify-internal-tasks,periodic-tasks,reporting-tasks,research-mode-tasks,retry-tasks,send-sms-high,send-sms-medium,send-sms-low,send-throttled-sms-tasks,send-email-high,send-email-medium,send-email-low,service-callbacks,service-callbacks-retry,delivery-receipts
