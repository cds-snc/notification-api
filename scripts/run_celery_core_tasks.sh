#!/bin/sh

set -e

# Runs celery with all celery queues except send-throttled-sms-tasks, 
# send-sms-* and send-email-*.

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency="${CELERY_CONCURRENCY-4}" -Q -priority-database-tasks.fifo,-normal-database-tasks,-bulk-database-tasks,job-tasks,notify-internal-tasks,periodic-tasks,priority-tasks,normal-tasks,bulk-tasks,reporting-tasks,research-mode-tasks,retry-tasks,service-callbacks,service-callbacks-retry,delivery-receipts
