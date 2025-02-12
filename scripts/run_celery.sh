#!/bin/sh

set -e

# Runs celery with all celery queues except the throtted sms queue.

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency="${CELERY_CONCURRENCY-4}" -Q database-tasks,-priority-database-tasks.fifo,-normal-database-tasks,-bulk-database-tasks,job-tasks,notify-internal-tasks,periodic-tasks,priority-tasks,normal-tasks,reporting-tasks,research-mode-tasks,retry-tasks,send-sms-high,send-sms-medium,send-sms-low,service-callbacks,service-callbacks-retry,delivery-receipts
