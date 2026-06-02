#!/bin/sh

set -e

# Runs celery with all celery queues except the throttled sms queue,
# periodic-tasks, and job-tasks.

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency="${CELERY_CONCURRENCY-4}" -Q -priority-database-tasks.fifo,-normal-database-tasks,-bulk-database-tasks,notify-internal-tasks,priority-tasks,normal-tasks,bulk-tasks,reporting-tasks,research-mode-tasks,retry-tasks,send-sms-high,send-sms-medium,send-sms-low,service-callbacks,service-callbacks-retry,delivery-receipts
